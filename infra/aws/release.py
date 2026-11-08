"""Release an already-pushed commit through the restricted SSM deployment document."""
import argparse
import json
import re
import subprocess
import time


def aws(region, *args):
    result = subprocess.run(["aws", *args, "--region", region, "--output", "json", "--no-cli-pager"], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("AWS release operation failed: " + args[0])
    return json.loads(result.stdout)


def release(region, stack_name, sha, migrate=True):
    if not re.fullmatch("[a-f0-9]{40}", sha):
        raise ValueError("Release requires a full commit SHA.")
    stack = aws(region, "cloudformation", "describe-stacks", "--stack-name", stack_name)["Stacks"][0]
    outputs = {entry["OutputKey"]: entry["OutputValue"] for entry in stack["Outputs"]}
    account = outputs["DeployRoleArn"].split(":")[4]
    def command(role, action):
        instance = outputs["AppInstance" if role == "app" else "WorkerInstance"]
        parameters = {"Role": [role], "Image": [f"{account}.dkr.ecr.{region}.amazonaws.com/findie-{role}:{sha}"],
            "Domain": [outputs["Domain"]], "WorkerHost": [outputs["WorkerHost"]], "RedisHost": [outputs["RedisHost"]],
            "MigrationRole": [outputs["MigrationRoleArn"]], "Action": [action]}
        result = aws(region, "ssm", "send-command", "--instance-ids", instance, "--document-name", outputs["DeployDocument"],
                     "--parameters", json.dumps(parameters), "--timeout-seconds", "1200")
        command_id = result["Command"]["CommandId"]
        deadline = time.monotonic() + 1250
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                invocation = aws(region, "ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", instance)
            except RuntimeError:
                continue
            status = invocation["Status"]
            if status == "Success":
                print(f"{action} {role}: success", flush=True)
                return
            if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
                raise RuntimeError(f"{action} {role} failed; inspect SSM command {command_id}.")
        raise RuntimeError(f"SSM command {command_id} timed out.")
    if migrate:
        command("app", "migrate")
        command("worker", "migrate")
    command("worker", "deploy")
    try:
        command("app", "deploy")
    except Exception:
        command("worker", "rollback")
        raise
    print("Release complete: https://" + outputs["Domain"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument("--stack", default="findie-production")
    parser.add_argument("--skip-migrations", action="store_true", help="Use only when the schema is already verified at this release.")
    args = parser.parse_args()
    release(args.region, args.stack, args.sha, not args.skip_migrations)
