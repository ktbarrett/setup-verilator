# Setup Verilator

Install a specific version of [Verilator](https://github.com/verilator/verilator) in GitHub Actions:

```yaml
steps:
  - uses: ktbarrett/setup-verilator@dev
    with:
      version: '5.048'
  - run: verilator --version
```

Both `5.048` and `v5.048` select the same upstream release.
Use `version: nightly` to install the latest successfully published nightly,
or `version: master` to install the latest master commit from source.

If builds for the given version and architecture are available on
[ktbarrett/verilator-builds](https://github.com/ktbarrett/verilator-builds),
those are used, otherwise Verilator is built from source and the Action will
source the necessary dependencies to do so.

## Platform Support

We only support the following official Github Runners,
but private runners running similar operating systems should also work.

* `ubuntu-22.04`
* `ubuntu-22.04-arm`
* `ubuntu-24.04`
* `ubuntu-24.04-arm`
* `ubuntu-26.04`
* `ubuntu-24.04-arm`
* `macos-14`
* `macos-15`
* `macos-15-intel`
* `macos-26`
* `macos-26-intel`

## Action Inputs

| Input | Default | Description |
| --- | --- | --- |
| `version` | Required | An upstream release version, with optional `v`, or `nightly` |
| `token` | `${{ github.token }}` | Token for GitHub metadata and downloads; no write permission needed |
| `install-dependencies` | `'true'` | Install missing runtime tools and source build dependencies |
| `force-source` | `'false'` | Always build from source; `nightly` builds current upstream `master` |
| `jobs` | `'2'` | Parallel compilation jobs for source builds |

## Action Outputs

| Output | Description |
| --- | --- |
| `version` | Installed upstream version, including the `v` prefix |
| `path` | Installation prefix; the Verilator executable is at `<path>/bin/verilator` |
| `source-sha` | Full upstream commit SHA used by the installation |
| `built-from-source` | `'true'` if Verilator was built from source, or `'false'` if a prebuilt package was used |

Use the setup step's `id` to access its outputs in later steps:

```yaml
- uses: ktbarrett/setup-verilator@dev
  id: verilator
  with:
    version: nightly
- name: Show installation details
  env:
    VERILATOR_VERSION: ${{ steps.verilator.outputs.version }}
    VERILATOR_PATH: ${{ steps.verilator.outputs.path }}
    VERILATOR_SOURCE_SHA: ${{ steps.verilator.outputs.source-sha }}
    VERILATOR_BUILT_FROM_SOURCE: ${{ steps.verilator.outputs.built-from-source }}
  run: |
    echo "Version: $VERILATOR_VERSION"
    echo "Installation prefix: $VERILATOR_PATH"
    echo "Source commit: $VERILATOR_SOURCE_SHA"
    echo "Built from source: $VERILATOR_BUILT_FROM_SOURCE"
```
