# PICS Package Process (`pkg_processor`)

A Python tool to process 1206:2025 compliant deliverables and convert them to Master Wav DTBs (i.e. Universal/Agnostic).

## Installation

You can install the tool in editable mode using `pip`:

```bash
pip install -e .
```

## Usage

Run the tool using the command-line interface:

```bash
pkg-processor <path-to-pkg.zip> [options]
```

### Options

*   `-o, --output-dir`: Directory where the output master.zip will be saved.
*   `-k, --keep`: Preserve the fully converted DTB folder structure directly under `{output_dir}/{prodID}` (useful for manual testing/inspection).

## AMR-WB+ Decoder Notice

> [!IMPORTANT]
> The AMR-WB+ codec is patent-protected, and its distribution is controlled by the National Library Service (NLS). Authorized users must contact the NLS PICS Admin in order to acquire the codec.
