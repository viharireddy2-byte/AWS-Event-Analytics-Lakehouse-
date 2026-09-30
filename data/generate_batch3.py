"""Generate a nonoverlapping event batch; upload events only, reuse user snapshot."""
import argparse
from generate_large_dataset import generate
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".generated/batch3")
    parser.add_argument("--events", type=int, default=1000000)
    args = parser.parse_args()
    generate(args.output, args.events, 1000000, start_id=50000001)
