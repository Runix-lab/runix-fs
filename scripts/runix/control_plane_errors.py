"""Shared sanitized HTTP errors for the API and optional browser wrapper."""


class HttpError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
