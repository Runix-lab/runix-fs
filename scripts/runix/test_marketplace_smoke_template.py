"""Guard the approved resource inventory and tenant network/IAM boundaries."""

import json
import unittest

from marketplace_smoke_template import template


class SmokeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.document = template()
        self.resources = self.document["Resources"]

    def of_type(self, kind):
        return [value["Properties"] for value in self.resources.values()
                if value["Type"] == "AWS::" + kind]

    def test_inventory_matches_approved_budget(self):
        self.assertEqual(len(self.of_type("EC2::Instance")), 4)
        self.assertEqual(len(self.of_type("EC2::VPC")), 2)
        endpoints = self.of_type("EC2::VPCEndpoint")
        self.assertEqual(sum(item["VpcEndpointType"] == "Interface" for item in endpoints), 4)
        self.assertEqual(sum(item["VpcEndpointType"] == "Gateway" for item in endpoints), 2)
        size = 0
        for instance in self.of_type("EC2::Instance"):
            self.assertEqual(instance["InstanceType"], "t3.large")
            self.assertEqual(instance["CreditSpecification"], {"CPUCredits": "standard"})
            for mapping in instance["BlockDeviceMappings"]:
                self.assertTrue(mapping["Ebs"]["Encrypted"])
                self.assertTrue(mapping["Ebs"]["DeleteOnTermination"])
                size += mapping["Ebs"]["VolumeSize"]
        self.assertEqual(size, 160)

    def test_no_public_routes_addresses_or_listeners(self):
        for forbidden in ("EC2::InternetGateway", "EC2::NatGateway", "EC2::EIP", "EC2::Route"):
            self.assertEqual(self.of_type(forbidden), [])
        for subnet in self.of_type("EC2::Subnet"):
            self.assertFalse(subnet["MapPublicIpOnLaunch"])
        for group in self.of_type("EC2::SecurityGroup"):
            for rule in group.get("SecurityGroupIngress", []):
                self.assertNotIn("CidrIp", rule)
                self.assertNotIn("CidrIpv6", rule)
            self.assertTrue(group["SecurityGroupEgress"])
        self.assertNotIn("0.0.0.0/0", json.dumps(self.document))

    def test_tenants_have_distinct_networks_and_storage_policies(self):
        for tenant, other in (("Alpha", "Beta"), ("Beta", "Alpha")):
            role = self.resources[tenant + "Role"]["Properties"]
            serialized = json.dumps(role)
            self.assertNotIn(other, serialized)
            self.assertIn(tenant + "Data", serialized)
            for kind in ("Master", "Worker"):
                instance = self.resources[tenant + kind]["Properties"]
                self.assertEqual(instance["SubnetId"], {"Ref": tenant + "Subnet"})
                self.assertEqual(instance["MetadataOptions"]["HttpTokens"], "required")
                self.assertNotIn("UserData", instance)

    def test_object_access_scoped_and_no_account_admin(self):
        for role in self.of_type("IAM::Role"):
            self.assertNotIn("ManagedPolicyArns", role)
            self.assertEqual(role["AssumeRolePolicyDocument"]["Statement"][0]["Principal"],
                             {"Service": "ec2.amazonaws.com"})
            for policy in role["Policies"]:
                for statement in policy["PolicyDocument"]["Statement"]:
                    for action in statement["Action"]:
                        self.assertNotIn("*", action)
                        if action.startswith("s3:"):
                            self.assertNotEqual(statement["Resource"], "*")
        for bucket in self.of_type("S3::Bucket"):
            self.assertTrue(all(bucket["PublicAccessBlockConfiguration"].values()))
        for resource in self.resources.values():
            if resource["Type"] in {"AWS::EC2::Instance", "AWS::IAM::Role"}:
                self.assertIn({"Key": "ExpiresAt", "Value": {"Ref": "ExpiresAt"}}, resource["Properties"]["Tags"])

    def test_references_are_resolvable(self):
        available = set(self.resources) | set(self.document["Parameters"])
        def check(value):
            if isinstance(value, dict):
                if "Ref" in value:
                    self.assertIn(value["Ref"], available)
                if "Fn::GetAtt" in value:
                    self.assertIn(value["Fn::GetAtt"][0], self.resources)
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        check(self.document)
        self.assertEqual(template(), self.document)


if __name__ == "__main__":
    unittest.main()
