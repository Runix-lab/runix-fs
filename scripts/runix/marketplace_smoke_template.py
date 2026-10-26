"""Generate the approved private smoke-test topology; never deploy resources."""

import json


def ref(name):
    return {"Ref": name}


def attr(name, attribute):
    return {"Fn::GetAtt": [name, attribute]}


def sub(value):
    return {"Fn::Sub": value}


def template():
    resources = {}
    outputs = {}
    tags = [{"Key": "Task", "Value": "runix-fs-marketplace-smoke"},
            {"Key": "Owner", "Value": "Runix"},
            {"Key": "ExpiresAt", "Value": ref("ExpiresAt")}]

    def add(name, kind, properties):
        resources[name] = {"Type": "AWS::" + kind, "Properties": properties}

    def bucket(name):
        add(name, "S3::Bucket", {
            "BucketEncryption": {"ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]},
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "BlockPublicPolicy": True,
                "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
            },
            "Tags": tags,
        })
        add(name + "Policy", "S3::BucketPolicy", {
            "Bucket": ref(name),
            "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
                "Effect": "Deny", "Principal": "*", "Action": "s3:*",
                "Resource": [attr(name, "Arn"), sub("${" + name + ".Arn}/*")],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }]},
        })
        outputs[name] = {"Value": ref(name)}

    bucket("Artifacts")
    for tenant, cidr in (("Alpha", "10.81.0.0/16"), ("Beta", "10.82.0.0/16")):
        vpc = tenant + "Vpc"
        subnet = tenant + "Subnet"
        nodes = tenant + "Nodes"
        endpoints = tenant + "Endpoints"
        data = tenant + "Data"
        role = tenant + "Role"
        profile = tenant + "Profile"
        bucket(data)
        add(vpc, "EC2::VPC", {
            "CidrBlock": cidr, "EnableDnsSupport": True,
            "EnableDnsHostnames": True, "Tags": tags,
        })
        add(subnet, "EC2::Subnet", {
            "VpcId": ref(vpc), "CidrBlock": cidr.replace("0.0/16", "1.0/24"),
            "AvailabilityZone": {"Fn::Select": [0, {"Fn::GetAZs": ""}]},
            "MapPublicIpOnLaunch": False, "Tags": tags,
        })
        route_table = tenant + "Routes"
        add(route_table, "EC2::RouteTable", {"VpcId": ref(vpc), "Tags": tags})
        add(tenant + "RouteAssociation", "EC2::SubnetRouteTableAssociation", {
            "SubnetId": ref(subnet), "RouteTableId": ref(route_table),
        })
        add(nodes, "EC2::SecurityGroup", {
            "GroupDescription": "Private Runix smoke-test nodes",
            "VpcId": ref(vpc), "Tags": tags,
            "SecurityGroupEgress": [{"IpProtocol": "tcp", "FromPort": 443,
                                     "ToPort": 443, "DestinationPrefixListId": ref("S3PrefixListId")}],
        })
        add(endpoints, "EC2::SecurityGroup", {
            "GroupDescription": "SSM HTTPS from test nodes only",
            "VpcId": ref(vpc), "Tags": tags,
            "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 443,
                                      "ToPort": 443, "SourceSecurityGroupId": ref(nodes)}],
            "SecurityGroupEgress": [{"IpProtocol": "tcp", "FromPort": 443,
                                     "ToPort": 443, "CidrIp": "127.0.0.1/32"}],
        })
        add(tenant + "NodeHttps", "EC2::SecurityGroupEgress", {
            "GroupId": ref(nodes), "IpProtocol": "tcp", "FromPort": 443,
            "ToPort": 443, "DestinationSecurityGroupId": ref(endpoints),
        })
        for label, start, end in (("Rpc", 8995, 8997), ("Management", 9000, 9002)):
            add(tenant + label + "Ingress", "EC2::SecurityGroupIngress", {
                "GroupId": ref(nodes), "IpProtocol": "tcp", "FromPort": start,
                "ToPort": end, "SourceSecurityGroupId": ref(nodes),
            })
            add(tenant + label + "Egress", "EC2::SecurityGroupEgress", {
                "GroupId": ref(nodes), "IpProtocol": "tcp", "FromPort": start,
                "ToPort": end, "DestinationSecurityGroupId": ref(nodes),
            })
        for service in ("ssm", "ssmmessages"):
            add(tenant + service + "Endpoint", "EC2::VPCEndpoint", {
                "VpcId": ref(vpc), "VpcEndpointType": "Interface",
                "ServiceName": sub("com.amazonaws.${AWS::Region}." + service),
                "SubnetIds": [ref(subnet)], "SecurityGroupIds": [ref(endpoints)],
                "PrivateDnsEnabled": True,
            })
        add(tenant + "S3Endpoint", "EC2::VPCEndpoint", {
            "VpcId": ref(vpc), "VpcEndpointType": "Gateway",
            "ServiceName": sub("com.amazonaws.${AWS::Region}.s3"),
            "RouteTableIds": [ref(route_table)],
        })
        add(role, "IAM::Role", {
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }]},
            "Policies": [{"PolicyName": "RunixSyntheticSmokeOnly", "PolicyDocument": {
                "Version": "2012-10-17", "Statement": [
                    {"Effect": "Allow", "Action": ["ssm:UpdateInstanceInformation",
                        "ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel",
                        "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"],
                     "Resource": "*"},
                    {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": attr(data, "Arn")},
                    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                     "Resource": sub("${" + data + ".Arn}/synthetic/*")},
                    {"Effect": "Allow", "Action": ["s3:GetObject"],
                     "Resource": sub("${Artifacts.Arn}/build/*")},
                ],
            }}], "Tags": tags,
        })
        add(profile, "IAM::InstanceProfile", {"Roles": [ref(role)]})
        for kind in ("Master", "Worker"):
            mappings = [{"DeviceName": "/dev/xvda", "Ebs": {
                "Encrypted": True, "DeleteOnTermination": True,
                "VolumeSize": 20, "VolumeType": "gp3",
            }}]
            if kind == "Worker":
                mappings.append({"DeviceName": "/dev/xvdb", "Ebs": {
                    "Encrypted": True, "DeleteOnTermination": True,
                    "VolumeSize": 40, "VolumeType": "gp3",
                }})
            name = tenant + kind
            add(name, "EC2::Instance", {
                "ImageId": ref("AmiId"), "InstanceType": "t3.large",
                "CreditSpecification": {"CPUCredits": "standard"},
                "IamInstanceProfile": ref(profile), "SubnetId": ref(subnet),
                "SecurityGroupIds": [ref(nodes)], "BlockDeviceMappings": mappings,
                "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                "Tags": tags + [{"Key": "Name", "Value": "runix-smoke-" + name}],
            })
            outputs[name] = {"Value": ref(name)}
            outputs[name + "Ip"] = {"Value": attr(name, "PrivateIp")}
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Runix synthetic private smoke test; no automatic engine success or production service",
        "Parameters": {
            "AmiId": {"Type": "AWS::EC2::Image::Id"},
            "S3PrefixListId": {"Type": "String", "AllowedPattern": "pl-[a-f0-9]+"},
            "ExpiresAt": {"Type": "String", "AllowedPattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"},
        },
        "Resources": resources, "Outputs": outputs,
    }


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))
