"""Static deployment safety checks that do not contact production or read secrets."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('aws_stack', ROOT / 'infra/aws/stack.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AwsDeploymentTests(unittest.TestCase):
    def test_automatic_release_never_migrates_and_rolls_worker_back_if_app_fails(self):
        release_spec = importlib.util.spec_from_file_location('aws_release', ROOT / 'infra/aws/release.py')
        release_module = importlib.util.module_from_spec(release_spec)
        release_spec.loader.exec_module(release_module)
        outputs = {'DeployRoleArn': 'arn:aws:iam::123456789012:role/deploy', 'Domain': 'example.cloudfront.net',
                   'AppInstance': 'app', 'WorkerInstance': 'worker', 'WorkerHost': '10.0.0.1',
                   'RedisHost': 'redis.internal', 'MigrationRoleArn': 'migration', 'DeployDocument': 'document'}
        commands = []
        def aws(_region, *args):
            if args[:2] == ('cloudformation', 'describe-stacks'):
                return {'Stacks': [{'Outputs': [{'OutputKey': key, 'OutputValue': value} for key, value in outputs.items()]}]}
            if args[:2] == ('ssm', 'send-command'):
                parameters = json.loads(args[args.index('--parameters') + 1])
                commands.append((parameters['Role'][0], parameters['Action'][0]))
                return {'Command': {'CommandId': 'command'}}
            return {'Status': 'Failed' if commands[-1] == ('app', 'deploy') else 'Success'}
        with patch.object(release_module, 'aws', side_effect=aws), patch.object(release_module.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                release_module.release('region', 'stack', 'a' * 40)
        self.assertEqual(commands, [('worker', 'deploy'), ('app', 'deploy'), ('worker', 'rollback')])

    def test_private_network_and_oidc_scope(self):
        template = module.template()
        resources = template['Resources']
        json.dumps(template)
        instances = [r['Properties'] for r in resources.values() if r['Type'] == 'AWS::EC2::Instance']
        self.assertEqual(len(instances), 2)
        for instance in instances:
            self.assertEqual(instance['MetadataOptions']['HttpTokens'], 'required')
            self.assertEqual(instance['MetadataOptions']['HttpPutResponseHopLimit'], 1)
            self.assertNotIn('AssociatePublicIpAddress', instance)
        self.assertFalse(resources['Broker']['Properties']['PubliclyAccessible'])
        self.assertTrue(resources['Cache']['Properties']['TransitEncryptionEnabled'])
        trust = resources['DeployRole']['Properties']['AssumeRolePolicyDocument']['Statement'][0]
        conditions = trust['Condition']['StringEquals']
        self.assertEqual(conditions['token.actions.githubusercontent.com:aud'], 'sts.amazonaws.com')
        self.assertNotIn('StringLike', trust['Condition'])

    def test_cloudfront_cannot_cache_sessions_and_starts_disabled(self):
        template = module.template()
        config = template['Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertEqual(template['Parameters']['EnableDistribution']['Default'], 'false')
        self.assertEqual(config['DefaultCacheBehavior']['CachePolicyId'], '4135ea2d-6df8-44a3-9df3-4b5a84be39ad')
        self.assertEqual(config['DefaultCacheBehavior']['ViewerProtocolPolicy'], 'redirect-to-https')

    def test_build_context_excludes_secrets_and_local_data(self):
        ignored = (ROOT / '.dockerignore').read_text().splitlines()
        for value in ('**/.env', '**/.env*', '**/env.before', '.cache', '.git'):
            self.assertIn(value, ignored)


if __name__ == '__main__':
    unittest.main()
