# idp-platform

A small Internal Developer Platform CLI. One command scaffolds a production-ready
FastAPI service with Docker, Terraform for Azure Container Apps, a GitHub Actions
pipeline, tests and monitoring:

```bash
platform create orders-api
```

## Install

```bash
pip install .            # or: pip install -e .  while developing the CLI
platform --version
platform doctor          # checks git, docker, terraform, az, gh
```

Without installing: `python -m idp_platform create orders-api`.

## Create a service

```bash
platform create orders-api
platform create orders-api --region westeurope --python-version 3.13 --acr-sku Standard
platform create orders-api --output-dir ~/projects --no-git
```

Names: 3-20 lowercase letters, digits and single hyphens, starting with a letter
(they become part of Azure resource names, which have strict limits).

The new folder is a git repo with one commit, ready to push. Its README walks
through the one-time Azure setup.

```
orders-api/
├── app/                  FastAPI app: /health /ready /info /metrics + example API
├── tests/
├── terraform/            RG, ACR, Log Analytics, App Insights, Container App, alerts
├── scripts/              one-time Azure bootstrap (state storage + GitHub OIDC)
├── .github/workflows/    test, build, deploy, pipeline
├── Dockerfile            multi-stage, non-root
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Developing the CLI

```bash
python -m unittest discover -s tests -v     # or: pytest
```

Templates live in `idp_platform/templates/fastapi-service/` as ordinary files.
`__PLACEHOLDER__` tokens are substituted on create, and files named `dot-*` are
written as `.*` (`dot-github` becomes `.github`), because packaging tools drop
real dotfiles.

The CLI module isn't called `platform.py` on purpose: that name shadows Python's
standard-library `platform` module, which breaks other tools run from the same
folder.
