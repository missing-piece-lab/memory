"""Keeps the tests offline when a production .env sits in the checkout (the README puts one there): the engine's CLIs
read ./.env, so every test runs with ENV_FILE pointed at nothing and the production variables dropped. run.py and pytest both."""
import os

PROD = ("GRAPH_", "EMBED_", "MODEL_", "RECALL_", "HOOK_", "PG", "VERIFIER_", "GARDENER_", "REVIEW_", "IDENTITY_")


def offline_env(env=None):
    env = {k: v for k, v in (env or os.environ).items() if not k.startswith(PROD)}
    env["ENV_FILE"] = os.devnull
    return env


_env = offline_env()
os.environ.clear()
os.environ.update(_env)
