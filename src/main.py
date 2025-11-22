import os
import sys
import asyncio
import argparse
import logging
from typing import Optional

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tqdm import tqdm

from src.generate import generate_to_file
from src.verify import verify_file


class TqdmLoggingHandler(logging.StreamHandler):
    def __init__(self, level=logging.NOTSET):
        super().__init__()

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def configure_logging() -> None:
    os.makedirs('logs', exist_ok=True)

    for handler in logging.root.handlers[:]:
        if isinstance(handler, logging.StreamHandler):
            logging.root.removeHandler(handler)

    # Use tqdm-friendly output in interactive terminals
    if sys.stdout.isatty():
        stream_handler = TqdmLoggingHandler()
    else:
        stream_handler = logging.StreamHandler(sys.stdout)

    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.root.addHandler(stream_handler)

    file_handler = logging.FileHandler(os.path.join('logs', 'pipeline.log'), encoding='utf-8', mode='a')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.root.addHandler(file_handler)

    logging.root.setLevel(logging.INFO)


async def run_generation(model: str, dataset: str, n: int, k: int, api_key: Optional[str], mode: str) -> str:
    # reuse the unified api of generate.py to avoid duplicate logic
    output_file = await generate_to_file(
        model=model,
        dataset=dataset,
        n=n,
        k=k,
        api_key=api_key,
        mode=mode,
        concurrency=150,
    )
    logging.getLogger(__name__).info("Generation stage completed")
    return output_file


async def main_async():
    parser = argparse.ArgumentParser(description="Pipeline: generate first, then verify")
    parser.add_argument("--model", type=str, required=True, help="Model name to evaluate")
    parser.add_argument("--dataset", type=str, required=True, help="Path to dataset file")
    parser.add_argument("--n", type=int, default=10, help="Number of problems to process")
    parser.add_argument("--k", type=int, default=1, help="Attempts per problem")
    parser.add_argument("--api_key", type=str, help="API key (falls back to env if omitted)")
    parser.add_argument("--mode", type=str, default="lean", help="Prompt mode (default: lean)")
    parser.add_argument("--timeout", type=int, default=None, help="Verification timeout (override config)")
    parser.add_argument("--max_workers", type=int, default=None, help="Verification max concurrency (override config)")
    args = parser.parse_args()

    configure_logging()
    logger = logging.getLogger(__name__)

    # 1) Generation
    gen_output = await run_generation(
        model=args.model,
        dataset=args.dataset,
        n=args.n,
        k=args.k,
        api_key=args.api_key,
        mode=args.mode,
    )
    logger.info(f"Generation output: {gen_output}")

    # 2) Verification (supports direct function calls, also retains src.verify's CLI usage)
    verify_output = verify_file(gen_output, timeout=args.timeout, max_workers=args.max_workers)
    logger.info(f"Verification output: {verify_output}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


