// Copyright 2025 OPPO.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use crate::master::journal::{JournalBatch, JournalEntry};
use crate::master::{Master, MasterMetrics};
use curvine_config::JournalConf;
use curvine_core_error::CommonResult;
use curvine_error::FsResult;
use curvine_raft::raft::RaftClient;
use curvine_runtime::common::SerdeUtils;
use curvine_runtime::common::{LocalTime, TimeSpent};
use curvine_runtime::sync::channel::BlockingReceiver;
use std::sync::mpsc::{self, RecvTimeoutError, TryRecvError};
use std::thread;
use std::time::Duration;

// Runix Lab modification (2026-10-30): flush queued entries before commit acknowledgements.

pub struct SenderTask {
    pub(crate) client: RaftClient,
    pub(crate) batch: JournalBatch,
    pub(crate) flush_batch_ms: u64,
    pub(crate) flush_batch_size: u64,
    pub(crate) last_flush_ms: u64,
    pub(crate) metrics: &'static MasterMetrics,
}

impl SenderTask {
    pub fn new(client: RaftClient, conf: &JournalConf, batch_seq_id: u64) -> CommonResult<Self> {
        let sender = Self {
            client,
            batch: JournalBatch::new(batch_seq_id),
            flush_batch_ms: conf.writer_flush_batch_ms,
            flush_batch_size: conf.writer_flush_batch_size,
            last_flush_ms: LocalTime::mills(),
            metrics: Master::get_metrics()?,
        };

        Ok(sender)
    }

    // Start a thread to execute sender task
    pub fn spawn(
        self,
        receiver: BlockingReceiver<JournalEntry>,
        commits: mpsc::Receiver<mpsc::Sender<FsResult<()>>>,
    ) -> FsResult<()> {
        // Commit requests use a separate channel, so they cannot fill a bounded
        // entry queue while Raft apply emits its UFS-applied progress entry.
        let poll = Duration::from_millis(self.flush_batch_ms.clamp(1, 10));
        let name = "journal-writer".to_string();
        let task = self;
        thread::Builder::new().name(name.clone()).spawn(move || {
            if let Err(e) = Self::loop0(receiver, commits, poll, task) {
                log::error!("thread {} stop: {:?}; aborting master", name, e);
                std::process::abort();
            }
        })?;
        Ok(())
    }

    fn loop0(
        receiver: BlockingReceiver<JournalEntry>,
        commits: mpsc::Receiver<mpsc::Sender<FsResult<()>>>,
        poll: Duration,
        mut task: SenderTask,
    ) -> FsResult<()> {
        // The thread should not end.
        loop {
            let event = match receiver.recv_timeout(poll) {
                Ok(v) => Some(v),
                Err(RecvTimeoutError::Timeout) => None,
                Err(RecvTimeoutError::Disconnected) => {
                    task.flush_pending()?;
                    return Ok(());
                }
            };
            task.handle(event)?;
            while let Ok(ack) = commits.try_recv() {
                let client = task.client.clone();
                task.commit_queued_with(&receiver, ack, &mut |bytes| {
                    Ok(client.block_on_send_propose(bytes)?)
                })?;
            }
        }
    }

    pub fn handle(&mut self, entry: Option<JournalEntry>) -> FsResult<()> {
        let client = self.client.clone();
        self.handle_with(entry, &mut |bytes| Ok(client.block_on_send_propose(bytes)?))
    }

    fn handle_with(
        &mut self,
        entry: Option<JournalEntry>,
        propose: &mut impl FnMut(Vec<u8>) -> FsResult<()>,
    ) -> FsResult<()> {
        let force = if let Some(v) = entry {
            let force = matches!(v, JournalEntry::Snapshot(_));
            self.batch.push(v);
            self.metrics.journal_queue_len.dec();
            force
        } else {
            false
        };

        let len = self.batch.len() as u64;
        if len == 0 {
            return Ok(());
        }

        if force || len >= self.flush_batch_size || self.flush_interval_elapsed() {
            self.flush_pending_with(propose)?;
        }

        Ok(())
    }

    fn flush_interval_elapsed(&self) -> bool {
        LocalTime::mills() - self.last_flush_ms >= self.flush_batch_ms
    }

    fn commit_queued_with(
        &mut self,
        receiver: &BlockingReceiver<JournalEntry>,
        ack: mpsc::Sender<FsResult<()>>,
        propose: &mut impl FnMut(Vec<u8>) -> FsResult<()>,
    ) -> FsResult<()> {
        // A caller sends its fence only after all of its mutation entries have
        // been handed off. Drain to Empty (or closed) before the forced flush.
        // No entry sequence/frontier is inferred from racing producer counters.
        loop {
            match receiver.try_recv() {
                Ok(entry) => self.handle_with(Some(entry), propose)?,
                Err(TryRecvError::Empty | TryRecvError::Disconnected) => break,
            }
        }
        self.flush_pending_with(propose)?;
        // A caller may have timed out. The real commit still stands; a dropped
        // waiter must not turn a successful Raft apply into a master abort.
        let _ = ack.send(Ok(()));
        Ok(())
    }

    fn flush_pending(&mut self) -> FsResult<()> {
        let client = self.client.clone();
        self.flush_pending_with(&mut |bytes| Ok(client.block_on_send_propose(bytes)?))
    }

    fn flush_pending_with(
        &mut self,
        propose: &mut impl FnMut(Vec<u8>) -> FsResult<()>,
    ) -> FsResult<()> {
        if self.batch.is_empty() {
            return Ok(());
        }

        let spend = TimeSpent::new();

        let bytes = SerdeUtils::serialize(&self.batch)?;
        propose(bytes)?;

        self.metrics.journal_flush_count.inc();
        self.metrics
            .journal_flush_time
            .inc_by(spend.used_us() as i64);

        // Scroll to the next batch.
        self.batch.next();
        self.last_flush_ms = LocalTime::mills();

        Ok(())
    }
}

#[cfg(test)]
mod commit_tests {
    use super::*;
    use crate::master::journal::UfsAppliedEntry;
    use curvine_error::FsError;
    use curvine_runtime::sync::channel::BlockingChannel;

    fn task() -> SenderTask {
        Master::init_test_metrics();
        let conf = JournalConf {
            writer_flush_batch_ms: 60000,
            writer_flush_batch_size: 1000,
            ..Default::default()
        };
        let client = RaftClient::from_conf(conf.create_runtime(), &conf);
        SenderTask::new(client, &conf, 0).unwrap()
    }

    fn entry(id: u64) -> JournalEntry {
        JournalEntry::UfsApplied(UfsAppliedEntry {
            op_id: id,
            rpc_id: 0,
            term: 1,
            index: id,
        })
    }

    #[test]
    fn commit_forces_partial_batch_preserves_order_and_waits_for_proposal() {
        let mut task = task();
        let (tx, rx) = BlockingChannel::new(0).split();
        task.handle_with(Some(entry(1)), &mut |_| {
            panic!("partial batch must remain pending")
        })
        .unwrap();
        tx.send(entry(2)).unwrap();
        tx.send(entry(3)).unwrap();
        let (ack, result) = mpsc::channel();
        let mut proposals = 0;
        task.commit_queued_with(&rx, ack, &mut |bytes| {
            assert!(matches!(result.try_recv(), Err(TryRecvError::Empty)));
            let batch = JournalBatch::deserialize_compat(&bytes).unwrap();
            assert_eq!(
                batch.batch.iter().map(|e| e.op_id()).collect::<Vec<_>>(),
                vec![1, 2, 3]
            );
            proposals += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!(proposals, 1);
        assert!(result.try_recv().unwrap().is_ok());
        assert!(task.batch.is_empty());
        assert_eq!(task.batch.seq_id, 1);
    }

    #[test]
    fn failed_commit_keeps_pending_batch_and_never_acknowledges_success() {
        let mut task = task();
        let (tx, rx) = BlockingChannel::new(0).split();
        tx.send(entry(4)).unwrap();
        let (ack, result) = mpsc::channel();
        assert!(task
            .commit_queued_with(&rx, ack, &mut |_| Err(FsError::common(
                "Raft commit failed"
            )))
            .is_err());
        assert!(matches!(result.try_recv(), Err(TryRecvError::Disconnected)));
        assert_eq!(task.batch.len(), 1);
        assert_eq!(task.batch.seq_id, 0);
    }

    #[test]
    fn empty_barrier_never_fabricates_a_journal_entry_or_proposal() {
        let mut task = task();
        let (_tx, rx) = BlockingChannel::new(0).split();
        let (ack, result) = mpsc::channel();
        task.commit_queued_with(&rx, ack, &mut |_| panic!("empty fence must not propose"))
            .unwrap();
        assert!(result.try_recv().unwrap().is_ok());
        assert_eq!(task.batch.seq_id, 0);
    }

    #[test]
    fn expired_waiter_and_closed_entry_queue_do_not_erase_actual_commit() {
        let mut task = task();
        let (tx, rx) = BlockingChannel::new(1).split();
        tx.send(entry(5)).unwrap();
        drop(tx);
        let (ack, result) = mpsc::channel();
        drop(result);
        let mut calls = 0;
        task.commit_queued_with(&rx, ack, &mut |_| {
            calls += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!(calls, 1);
        assert!(task.batch.is_empty());
        let (ack, result) = mpsc::channel();
        task.commit_queued_with(&rx, ack, &mut |_| panic!("already committed"))
            .unwrap();
        assert!(result.try_recv().unwrap().is_ok());
    }
}
