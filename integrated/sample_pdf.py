"""Render the synthetic fixture without provider calls or delivery."""
import argparse
import json
from pathlib import Path
from integrated.cloud_review import make_review
from integrated.render import render

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='out/report-v2-synthetic.pdf')
    args=parser.parse_args()
    snapshot=json.loads((Path(__file__).parent/'tests/fixtures/snapshot.json').read_text())
    render(snapshot,make_review(snapshot),args.output)
    print(args.output)

if __name__=='__main__':main()
