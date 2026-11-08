"""Static deployment safety checks that do not contact production or read secrets."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('aws_stack', ROOT / 'infra/aws/stack.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AwsDeploymentTests(unittest.TestCase):
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
