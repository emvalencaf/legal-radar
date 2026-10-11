<a id="readme-top"></a>

<!-- Structure adapted from https://github.com/othneildrew/Best-README-Template -->

<br />
<div align="center">
  <h3 align="center">Legal Radar</h3>

  <p align="center">
    A RAG-based project that ingests a given legal topic (pointing to a law)
    and finds jurisprudence precedents, doctrine, and law amendments via the
    LexML Brasil portal.
    <br />
    <a href="CONTRIBUTING.md"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/emvalencaf/legal-radar/issues/new">Report Bug</a>
    &middot;
    <a href="https://github.com/emvalencaf/legal-radar/issues/new">Request Feature</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project

A RAG-based project that ingests a given legal topic (pointing to a law) and
finds jurisprudence precedents, doctrine, and law amendments via the
[LexML Brasil](https://www.lexml.gov.br/) portal.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [Python](https://www.python.org) managed with [uv](https://docs.astral.sh/uv/)
* [ruff](https://docs.astral.sh/ruff/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

<!-- Tools and versions needed before installing. -->

* [`uv`](https://docs.astral.sh/uv/)

### Installation

1. Clone the repository
   ```bash
   git clone https://github.com/emvalencaf/legal-radar.git
   cd legal-radar
   ```
2. Enable the git hooks
   ```bash
   scripts/setup.sh
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

Start Neo4j with docker compose and run the pipeline over the fixture lei:

```bash
scripts/skeleton.sh
```

Ingest the anchor leis of an assunto from LexML/Planalto (needs `uv sync --extra browser` and
`playwright install chromium`, since both sites reject plain HTTP clients):

```bash
uv run legal-radar ingest "desconsideração da personalidade jurídica"
```

Ingest the seed precedents (STJ Tema 1210, STF Tema 1232) and the top hits of each court. STJ's
Cloudflare check rejects bundled Chromium, so this needs Google Chrome installed:

```bash
uv run legal-radar ingest-jurisprudencia
```

Opt-in live smoke test against the real courts (not run by default): `uv run pytest -m live`.

Tests (need Docker for the Neo4j test container): `uv run pytest`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [ ] First milestone

See the [open issues](https://github.com/emvalencaf/legal-radar/issues) for proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions follow the branch strategy and commit convention in
[CONTRIBUTING.md](CONTRIBUTING.md): cut a branch from `development`, commit as
`tag(subject/subsubject): summary`, and open a pull request into `development`.
Coding and documentation rules are in [CODE_STANDARDS.md](CODE_STANDARDS.md).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

No license has been chosen yet.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contact

Edson Mota Valença Filho - [@emvalencaf](https://github.com/emvalencaf)

Project Link: [https://github.com/emvalencaf/legal-radar](https://github.com/emvalencaf/legal-radar)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
