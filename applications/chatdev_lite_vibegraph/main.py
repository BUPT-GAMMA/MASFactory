from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import OpenAIModel
from applications.chatdev_lite_vibegraph.workflow import build_chatdev_lite_vibegraph

parser = argparse.ArgumentParser(description='ChatDev command-line arguments')
parser.add_argument('--org', type=str, default="DefaultOrganization", help="Organization name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--task', type=str, default="Write a Ping-Pong (Pong) game, use Python and ultimately provide an application that can be run directly.", help="Task prompt for software development")
parser.add_argument('--name', type=str, default="PingPong", help="Software name; software will be generated in WareHouse/name_org_timestamp directory")
parser.add_argument('--model', type=str, default="gpt-4o-mini", help="Model name, default is gpt-4o-mini, follows OpenAI interface. If using base_url, follows base_url provider")
parser.add_argument('--api_key', type=str, default=None, help="API key, default is empty, uses environment variable OPENAI_API_KEY")
parser.add_argument('--base_url', type=str, default=None, help="API base URL, default is empty, uses environment variable BASE_URL")
args = parser.parse_args()

base_url = args.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
api_key = args.api_key or os.getenv("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("Missing OpenAI API key: set OPENAI_API_KEY or pass --api_key")
model: OpenAIModel = OpenAIModel(model_name=args.model, api_key=api_key, base_url=base_url)

graph = build_chatdev_lite_vibegraph(model=model)
graph.build()
start_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
graph.invoke(
    input={},
    attributes={
        "task": args.task,
        "project_name": args.name,
        "org_name": args.org,
        "start_time": start_time,
        "name": args.name,
        "org": args.org,
    },
)
