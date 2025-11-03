## FATE-Eval

This project is the official evaluation code for the [FATE benchmark](https://github.com/frenzymath/FATE-Eval). It is an open-source toolkit for generating and verifying Lean 4 solutions to math problems, with support for pass@k metrics and cost tracking.

### Features
-   Unified generation interface across commercial APIs
-   Lean 4 verification with static precheck and batched REPL verification
-   pass@k computation and result aggregation
-   Cost tracking for API calls

### Requirements
-   Python 3.11+
-   [Lean 4](https://github.com/leanprover/lean4) toolchain and `lake` installed if running local verification.

### Installation
```bash
pip install -r requirements.txt
```

### Quickstart
1.  Prepare your model configurations in `config/models.yaml` and verification configuration in `config/verify_config.yaml`.
2.  Prepare Lean Dependencies: This repository provides three versions of Lean workspaces under the `lean_workspaces` directory. Run 
    ```bash
    lake exe cache get
    ```
    in the corresponding directory before running verification or the full pipeline.
3.  Run generation only:
    ```bash
    python -m src.generate --model openai_o3 \
      --dataset data/FATE-H.json \
      --n 100 --k 1 --mode lean
    ```
4.  Run the full pipeline (generate then verify):
    ```bash
    python -m src.main --model openai_o3 \
      --dataset data/FATE-H.json \
      --n 100 --k 1 --mode lean
    ```

Outputs are saved under `output/generate/<model>/...`, and verification summaries are saved under `output/verify/...` or the paths configured in your YAML files.

**Command-Line Arguments**:
The `src/main.py` script for running the full generation and verification pipeline accepts the following arguments:

-   `--model (required)`: The name of the model to evaluate.
-   `--dataset (required)`: The path to the dataset file.
-   `--n (optional, default: 10)`: The number of problems to process.
-   `--k (optional, default: 1)`: The number of attempts per problem.
-   `--api_key (optional)`: The API key for model calls. If omitted, it falls back to environment variables.
-   `--mode (optional, default: "lean")`: Modes for different prompts.
-   `--timeout (optional)`: The timeout in seconds for a single verification task. Overrides the setting in the config file if provided.
-   `--max_workers (optional)`: The maximum number of concurrent workers for verification. Overrides the setting in the config file if provided.

### Directory Structure (Key Parts)
-   `src/`: Generation, verification, model interfaces, and Lean utilities
-   `config/`: YAML configuration files for models and verification
-   `output/`: Generated and verified results
-   `logs/`: Runtime logs
-   `lean_workspaces/`: Contains different versions of Lean workspaces

### License
MIT License. See the `LICENSE` file for details.