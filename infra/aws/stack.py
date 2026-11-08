"""Render CloudFormation without reading local environment files or credentials."""
import base64
import json
from pathlib import Path


def ref(name): return {"Ref": name}
def att(name, key): return {"Fn::GetAtt": [name, key]}
def sub(value): return {"Fn::Sub": value}
def policy(statements): return {"Version": "2012-10-17", "Statement": statements}
def allow(actions, resource): return {"Effect": "Allow", "Action": actions, "Resource": resource}


def template():
    resources = {}
    def add(name, kind, **properties):
        resources[name] = {"Type": "AWS::" + kind, "Properties": properties}
        return ref(name)
    parameters = {name: {"Type": kind} for name, kind in {
        "Vpc": "AWS::EC2::VPC::Id", "PublicSubnet": "AWS::EC2::Subnet::Id", "AvailabilityZone": "AWS::EC2::AvailabilityZone::Name",
        "RdsSecurityGroup": "AWS::EC2::SecurityGroup::Id", "CloudFrontPrefixList": "String", "Ami": "AWS::EC2::Image::Id"}.items()}
    parameters["GitHubSubject"] = {"Type": "String", "Default": "repo:qbael@197704624/HackathonSGU2026@1449042338:ref:refs/heads/main"}
    parameters["EnableDistribution"] = {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]}
    subnet = add("PrivateSubnet", "EC2::Subnet", VpcId=ref("Vpc"), AvailabilityZone=ref("AvailabilityZone"), CidrBlock="172.31.64.0/24",
                 MapPublicIpOnLaunch=False, Tags=[{"Key": "Name", "Value": "findie-private"}])
    add("NatIp", "EC2::EIP", Domain="vpc")
    nat = add("Nat", "EC2::NatGateway", AllocationId=att("NatIp", "AllocationId"), SubnetId=ref("PublicSubnet"))
    route = add("PrivateRoutes", "EC2::RouteTable", VpcId=ref("Vpc"))
    add("PrivateInternet", "EC2::Route", RouteTableId=route, DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat)
    add("PrivateAssociation", "EC2::SubnetRouteTableAssociation", RouteTableId=route, SubnetId=subnet)
    groups = {name: add(name + "Group", "EC2::SecurityGroup", VpcId=ref("Vpc"), GroupDescription="Findie private " + name)
              for name in ("App", "Worker", "Broker", "Cache")}
    def ingress(name, target, port, **source):
        add(name, "EC2::SecurityGroupIngress", GroupId=target, IpProtocol="tcp", FromPort=port, ToPort=port, **source)
    ingress("CloudFrontIngress", groups["App"], 8080, SourcePrefixListId=ref("CloudFrontPrefixList"))
    ingress("PrivateImages", groups["Worker"], 8000, SourceSecurityGroupId=groups["App"])
    for name in ("App", "Worker"):
        ingress(name + "Amqps", groups["Broker"], 5671, SourceSecurityGroupId=groups[name])
        ingress(name + "Database", ref("RdsSecurityGroup"), 5432, SourceSecurityGroupId=groups[name])
    ingress("BrokerManagement", groups["Broker"], 443, SourceSecurityGroupId=groups["App"])
    ingress("WorkerRedis", groups["Cache"], 6379, SourceSecurityGroupId=groups["Worker"])
    configs = {
        "Api": {"ConnectionStrings__Database": "", "Authentication__Google__ClientId": "", "Authentication__Google__ClientSecret": "",
                "Storage__Endpoint": "", "Storage__Bucket": "", "Storage__AccessKeyId": "", "Storage__SecretAccessKey": "", "RabbitMq__Uri": "",
                "Ai__EmbeddingModelId": "Qwen/Qwen3-VL-Embedding-2B", "Ai__EmbeddingRevision": "", "Ai__RedactionRevision": "", "ADMIN_EMAILS": ""},
        "Worker": {"AI_SEARCH_DSN": "", "AI_RABBITMQ_URL": "", "OLLAMA_BASE_URL": "", "OLLAMA_API_KEY": "",
                   "AI_EMBEDDING_MODEL": "Qwen/Qwen3-VL-Embedding-2B", "AI_EMBEDDING_REVISION": "", "AI_REDACTION_REVISION": "",
                   "AI_EMBEDDING_DIMENSIONS": "2048", "AI_IMAGE_SEARCH_ENABLED": "false"},
        "Migration": {"ConnectionStrings__Database": "", "AI_SEARCH_MIGRATION_DSN": ""}}
    for name, config in configs.items():
        add(name + "Secret", "SecretsManager::Secret", Name="findie/production/" + name.lower(), SecretString=json.dumps(config))
        resources[name + "Secret"].update(DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
    shared = add("SharedSecret", "SecretsManager::Secret", Name="findie/production/service-token", GenerateSecretString={"PasswordLength": 64, "ExcludePunctuation": True})
    admin = add("BrokerSecret", "SecretsManager::Secret", Name="findie/production/broker-admin", GenerateSecretString={
        "SecretStringTemplate": '{"username":"findie_admin"}', "GenerateStringKey": "password", "PasswordLength": 48, "ExcludePunctuation": True})
    add("Broker", "AmazonMQ::Broker", BrokerName="findie", EngineType="RABBITMQ", EngineVersion="4.3", HostInstanceType="mq.m7g.medium",
        DeploymentMode="SINGLE_INSTANCE", AutoMinorVersionUpgrade=True, PubliclyAccessible=False, SubnetIds=[subnet], SecurityGroups=[groups["Broker"]],
        Users=[{"Username": "findie_admin", "Password": sub("{{resolve:secretsmanager:${BrokerSecret}:SecretString:password}}" )}])
    add("CacheSubnets", "ElastiCache::SubnetGroup", Description="Findie private Redis", SubnetIds=[subnet])
    add("Cache", "ElastiCache::ReplicationGroup", ReplicationGroupDescription="Findie search cache", Engine="redis", CacheNodeType="cache.t4g.micro",
        NumCacheClusters=1, AutomaticFailoverEnabled=False, CacheSubnetGroupName=ref("CacheSubnets"), SecurityGroupIds=[groups["Cache"]],
        TransitEncryptionEnabled=True, AtRestEncryptionEnabled=True, SnapshotRetentionLimit=0)
    for name in ("App", "Worker"):
        add(name + "Repository", "ECR::Repository", RepositoryName="findie-" + name.lower(), ImageTagMutability="IMMUTABLE", ImageScanningConfiguration={"ScanOnPush": True})
        statements = [allow(["secretsmanager:GetSecretValue"], [ref("ApiSecret" if name == "App" else "WorkerSecret"), shared]),
            allow(["ecr:GetAuthorizationToken"], "*"), allow(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], att(name + "Repository", "Arn"))]
        add(name + "Role", "IAM::Role", AssumeRolePolicyDocument=policy([{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]),
            ManagedPolicyArns=["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"], Policies=[{"PolicyName": "runtime", "PolicyDocument": policy(statements)}])
        add(name + "Profile", "IAM::InstanceProfile", Roles=[ref(name + "Role")])
        userdata = """#!/bin/bash
set -eu
dnf install -y docker python3
systemctl enable --now docker
swapoff -a
mkdir -p /opt/findie /var/lib/findie/keyring
chown 1654:1654 /var/lib/findie/keyring
chmod 700 /var/lib/findie/keyring
echo '* hard core 0' >> /etc/security/limits.conf
"""
        add(name + "Instance", "EC2::Instance", ImageId=ref("Ami"), InstanceType="t3.small" if name == "App" else "t3.medium",
            IamInstanceProfile=ref(name + "Profile"), SubnetId=subnet, SecurityGroupIds=[groups[name]],
            MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
            BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 24, "VolumeType": "gp3", "Encrypted": True}}],
            UserData={"Fn::Base64": userdata}, Tags=[{"Key": "Name", "Value": "findie-" + name.lower()}, {"Key": "Application", "Value": "findie"}])
        resources[name + "Instance"]["DependsOn"] = ["PrivateInternet", "PrivateAssociation"]
    add("Origin", "CloudFront::VpcOrigin", VpcOriginEndpointConfig={"Name": "findie-app", "Arn": sub("arn:aws:ec2:${AWS::Region}:${AWS::AccountId}:instance/${AppInstance}"),
        "HTTPPort": 8080, "HTTPSPort": 443, "OriginProtocolPolicy": "http-only", "OriginSSLProtocols": ["TLSv1.2"]})
    add("Distribution", "CloudFront::Distribution", DistributionConfig={"Enabled": {"Fn::If": ["DistributionEnabled", True, False]},
        "Comment": "Findie private application", "HttpVersion": "http2and3", "PriceClass": "PriceClass_200",
        "Origins": [{"Id": "app", "DomainName": att("AppInstance", "PrivateDnsName"),
            "VpcOriginConfig": {"VpcOriginId": att("Origin", "Id"), "OriginReadTimeout": 60},
            "OriginCustomHeaders": [{"HeaderName": "X-Forwarded-Proto", "HeaderValue": "https"}]}],
        "DefaultCacheBehavior": {"TargetOriginId": "app", "ViewerProtocolPolicy": "redirect-to-https", "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
            "CachedMethods": ["GET", "HEAD"], "Compress": True, "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad", "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3"},
        "ViewerCertificate": {"CloudFrontDefaultCertificate": True}})
    add("MigrationRole", "IAM::Role", AssumeRolePolicyDocument=policy([{"Effect": "Allow", "Principal": {"AWS": [att("AppRole", "Arn"), att("WorkerRole", "Arn")]}, "Action": "sts:AssumeRole"}]),
        Policies=[{"PolicyName": "migration", "PolicyDocument": policy([
            allow(["secretsmanager:GetSecretValue"], ref("MigrationSecret")),
            allow(["rds:CreateDBSnapshot"], [sub("arn:aws:rds:${AWS::Region}:${AWS::AccountId}:db:findie-postgres"), sub("arn:aws:rds:${AWS::Region}:${AWS::AccountId}:snapshot:findie-predeploy-*")]),
            allow(["rds:AddTagsToResource"], sub("arn:aws:rds:${AWS::Region}:${AWS::AccountId}:snapshot:findie-predeploy-*")),
            allow(["rds:DescribeDBSnapshots"], "*")])}])
    add("AssumeMigration", "IAM::Policy", PolicyName="assume-migration", Roles=[ref("AppRole"), ref("WorkerRole")],
        PolicyDocument=policy([allow(["sts:AssumeRole"], att("MigrationRole", "Arn"))]))
    code = base64.b64encode(Path(__file__).with_name("deploy_host.py").read_bytes()).decode()
    add("DeployDocument", "SSM::Document", DocumentType="Command", Content={"schemaVersion": "2.2", "description": "Deploy Findie immutable images with rollback",
        "parameters": {"Role": {"type": "String", "allowedValues": ["app", "worker"]},
            "Image": {"type": "String", "allowedPattern": r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/findie-(app|worker):[a-f0-9]{40}"},
            "Domain": {"type": "String", "allowedPattern": r"[a-z0-9.-]+\.cloudfront\.net"},
            "WorkerHost": {"type": "String", "allowedPattern": "[0-9.]+"}, "RedisHost": {"type": "String", "allowedPattern": "[a-zA-Z0-9.-]+"},
            "Action": {"type": "String", "allowedValues": ["deploy", "rollback", "migrate"], "default": "deploy"},
            "MigrationRole": {"type": "String", "allowedPattern": "arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+"}},
        "mainSteps": [{"action": "aws:runShellScript", "name": "deploy", "inputs": {"timeoutSeconds": "1200", "runCommand": ["set -eu",
            "echo '" + code + "' | base64 -d > /opt/findie/deploy_host.py",
            "python3 /opt/findie/deploy_host.py '{{ Role }}' '{{ Image }}' '{{ Domain }}' '{{ WorkerHost }}' '{{ RedisHost }}' '{{ Action }}' '{{ MigrationRole }}'"]}}]})
    instance_arns = [sub("arn:aws:ec2:${AWS::Region}:${AWS::AccountId}:instance/${" + name + "Instance}") for name in ("App", "Worker")]
    add("DeployRole", "IAM::Role", AssumeRolePolicyDocument=policy([{"Effect": "Allow",
        "Principal": {"Federated": sub("arn:aws:iam::${AWS::AccountId}:oidc-provider/token.actions.githubusercontent.com")}, "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {"StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com", "token.actions.githubusercontent.com:sub": ref("GitHubSubject")}}}]),
        Policies=[{"PolicyName": "deploy", "PolicyDocument": policy([allow(["ecr:GetAuthorizationToken"], "*"),
            allow(["ecr:DescribeImages", "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], [att("AppRepository", "Arn"), att("WorkerRepository", "Arn")]),
            allow(["ssm:SendCommand"], instance_arns + [sub("arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:document/${DeployDocument}")]),
            allow(["ssm:GetCommandInvocation", "cloudformation:DescribeStacks"], "*")])}])
    outputs = {"Domain": att("Distribution", "DomainName"), "DistributionId": ref("Distribution"), "AppInstance": ref("AppInstance"), "WorkerInstance": ref("WorkerInstance"),
        "WorkerHost": att("WorkerInstance", "PrivateIp"), "RedisHost": att("Cache", "PrimaryEndPoint.Address"), "DeployRoleArn": att("DeployRole", "Arn"),
        "DeployDocument": ref("DeployDocument"), "BrokerId": ref("Broker"), "AppRoleArn": att("AppRole", "Arn"), "MigrationRoleArn": att("MigrationRole", "Arn")}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Findie CloudFront, two private EC2, Amazon MQ, Redis; existing RDS and R2",
            "Parameters": parameters, "Conditions": {"DistributionEnabled": {"Fn::Equals": [ref("EnableDistribution"), "true"]}},
            "Resources": resources, "Outputs": {name: {"Value": value} for name, value in outputs.items()}}


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))
