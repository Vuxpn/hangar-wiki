<p align="center">
  <img src="./hangar-logo.png" alt="Hangar" width="640" />
</p>

<p align="center">
  <a href="./LICENSE.txt"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" alt="License: AGPL-3.0" /></a>
  <img src="https://img.shields.io/badge/base-Hangar%200.1.0-informational.svg" alt="Based on Hangar 0.1.0" />
</p>

# Hangar Wiki

Self-hosted project management with a **workspace wiki** and a
**plane-sdk compatible `/api/v1`**.

This repository is a downstream build of
[Hangar](https://github.com/szymczag/hangar) `0.1.0`, itself an open-source fork of
[Plane](https://github.com/makeplane/plane). It keeps everything Hangar ships and
adds two features on top:

| Feature                           | What you get                                                                                                                                       |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Workspace wiki**                | Workspace-level pages organised into public or private collections, with nesting, archiving, members and the collaborative editor.                 |
| **plane-sdk compatible `/api/v1`** | API-key endpoints for work-item types, custom properties, worklogs, epics and the wiki, matching `plane-sdk` 0.3.1 so the Plane MCP server works. |

> [!NOTE]
> Hangar Wiki is not affiliated with, endorsed by, or supported by Plane Software,
> Inc. or by the Hangar maintainers. “Plane” and the Plane logo are trademarks of
> Plane Software, Inc.

## Contents

- [Features](#features)
- [Quick start (development)](#quick-start-development)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

## Features

### Workspace wiki

Open **Wiki** from the app rail, or go to `/<workspace-slug>/wiki`.

- **Collections** — group pages into public or private collections. Private
  collections have members with _view_, _comment_ or _edit_ access.
- **Page tree** — nest and reorder pages with drag and drop; archive and restore
  them.
- **Collaborative editing** — the same real-time editor as project pages, served
  by the live server as the `workspace_page` document type.
- **Search and assets** — wiki pages appear in workspace search, and their
  uploads follow the wiki access policy rather than project membership.
- **API** — session routes under `/api/workspaces/<slug>/wiki/` for the web app;
  API-key routes under `/api/v1/workspaces/<slug>/pages/` and
  `/api/v1/workspaces/<slug>/collections/`. Content written through the API
  reaches open editors immediately.

### plane-sdk compatible `/api/v1`

Paths and payloads match `plane-sdk` 0.3.1, so the official SDK and the Plane MCP
server reach Hangar's own features without changes:

| Area                     | Endpoints (under `/api/v1/workspaces/<slug>/`)                                    |
| ------------------------ | --------------------------------------------------------------------------------- |
| Feature flags            | `features/`, `projects/<id>/features/`                                            |
| Work-item types          | `projects/<id>/work-item-types/` and their property links                         |
| Custom properties        | property definitions, options and values on work items                            |
| Worklogs                 | `projects/<id>/work-items/<id>/worklogs/`, `projects/<id>/total-worklogs/`            |
| Epics                    | `projects/<id>/epics/`, `projects/<id>/epics/<id>/issues/`                        |
| Wiki                     | `pages/`, `collections/`, collection pages and members                            |

A project with time tracking disabled or without an Epic type answers `402`.
Malformed bodies answer `400`.

### Inherited from Hangar

Federated SSO (Google, OIDC, SAML 2.0), Epics as work items, custom work-item
types and properties, time tracking, capacity planning, secure email with optional
OpenPGP, Todoist CSV import, instance branding, workspace short links, project
duplication, Markdown in descriptions, a second factor for the instance console,
and an enforced Content-Security-Policy. Telemetry and release checks are **off
by default**. See [Documentation](#documentation).

## Quick start (development)

**Requirements:** Docker Engine with Compose, Node.js 22.22+, Corepack (pins the
pnpm version), and about 12 GB of RAM for the full stack.

```sh
git clone https://github.com/Vuxpn/hangar-wiki.git
cd hangar-wiki
./setup.sh                                        # creates the .env files
docker compose -f docker-compose-local.yml up -d  # Postgres, Valkey, RabbitMQ, MinIO, API, workers
pnpm dev                                          # web, admin and space dev servers
```

| Service              | URL                                 |
| -------------------- | ----------------------------------- |
| Web app              | <http://localhost:3000>             |
| Instance admin       | <http://localhost:3001/god-mode/>   |

Common commands:

| Command                                       | Purpose                                           |
| --------------------------------------------- | ------------------------------------------------- |
| `pnpm build`                                  | Build every package and app                       |
| `pnpm check`                                  | Format, lint, types and repository contracts      |
| `pnpm fix`                                    | Auto-fix formatting and lint                      |
| `pnpm turbo run <task> --filter=<package>`    | Run a task for a single package                   |

## Deployment

This is a development quick start, not a production guide. For production use
the Hangar deployment guides:

- [Docker Compose / Swarm / all-in-one](deployments/cli/community/README.md)
- [Kubernetes and Helm](docs/kubernetes/README.md) — evaluation only
- [Amazon SES, deliverability and OpenPGP](docs/aws-ses-email-operations.md)

Images for this repository are not published; build them from source with the
Dockerfiles under `apps/*` or the compose files at the repository root.

## Documentation

| Topic                                                                                   | Guide                                                                                                                                      |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Fork architecture, upstream sync and core-touch ledger                                  | [FORK.md](FORK.md)                                                                                                                         |
| Authorization model                                                                     | [docs/authorization-model.md](docs/authorization-model.md)                                                                                 |
| Federated SSO (Google, OIDC, SAML)                                                      | [docs/federated-sso-security.md](docs/federated-sso-security.md)                                                                           |
| Second factor for the console                                                           | [docs/god-mode-second-factor.md](docs/god-mode-second-factor.md)                                                                           |
| Epics as work items                                                                     | [docs/epics-as-work-items.md](docs/epics-as-work-items.md)                                                                                 |
| Capacity planning                                                                       | [docs/capacity-planner.md](docs/capacity-planner.md)                                                                                       |
| Markdown in descriptions                                                                | [docs/markdown-in-descriptions.md](docs/markdown-in-descriptions.md)                                                                       |
| Importing from Todoist                                                                  | [docs/importing-from-todoist.md](docs/importing-from-todoist.md)                                                                           |
| Email delivery and OpenPGP                                                              | [docs/email-delivery-and-openpgp.md](docs/email-delivery-and-openpgp.md), [technical reference](docs/email-technical-implementation-plan.md) |
| Content-Security-Policy, Trusted Types, sanitization                                    | [CSP](docs/content-security-policy.md), [Trusted Types](docs/trusted-types-plan.md), [sanitization](docs/rich-text-sanitization.md)        |
| Secure file uploads                                                                     | [docs/secure-file-uploads.md](docs/secure-file-uploads.md)                                                                                 |
| Branding, short links, project duplication                                              | [branding](docs/instance-branding.md), [short links](docs/workspace-short-links.md), [duplication](docs/duplicating-projects.md)            |
| Runner control plane                                                                    | [docs/hangar-runner-architecture.md](docs/hangar-runner-architecture.md)                                                                   |
| Release policy and notes                                                                | [docs/release-policy.md](docs/release-policy.md), [0.1.0 notes](docs/releases/hangar-v0.1.0.md)                                           |

## Repository layout

```text
apps/
  api/          Django REST API; fork code lives in plane/ext/ (wiki, api_v1, …)
  web/          Main web app; fork UI lives in the ce/ overlay
  admin/        Instance administration (god-mode)
  space/        Public project views
  live/         Real-time collaboration server (Hocuspocus)
packages/       Shared UI, editor, types, constants, i18n, state, CSP, …
charts/hangar/  Helm chart (evaluation)
deployments/    Docker, all-in-one and Kubernetes deployment assets
docs/           Feature, security and operations guides
```

Fork backend code is isolated in `apps/api/plane/ext/`; necessary edits to
upstream-owned files are small and listed in the [FORK.md](FORK.md) ledger, which
keeps merges from Hangar and Plane cheap.

## Testing

```sh
# Frontend and repository checks
pnpm check

# Backend (Django/pytest) in an isolated Docker stack
docker compose -f docker-compose-test.yml run --rm --build api-tests pytest
docker compose -f docker-compose-test.yml down -v
```

See [apps/api/tests/RUNNING_TESTS.md](apps/api/tests/RUNNING_TESTS.md) for
subsets and troubleshooting.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for the branch,
commit and review workflow. Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md), and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE.txt). Derived
from [Hangar](https://github.com/szymczag/hangar) and
[Plane](https://github.com/makeplane/plane); upstream copyright and license
notices are retained.
