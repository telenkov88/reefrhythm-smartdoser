import gzip
import shutil
import glob
import os

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--path", type=str, default="./src/",
                    help="path to files", required=False)


def gzip_file(input_file_path, output_file_path):
    with open(input_file_path, 'rb') as f_in:
        with gzip.open(output_file_path, 'wb', compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)


def compress(directory_path, pattern):
    full_pattern = os.path.join(directory_path, pattern)
    files = glob.glob(full_pattern)

    for file in files:
        # Construct the output file name by adding .gz extension
        output_file = file + '.gz'

        # Gzip the file
        gzip_file(file, output_file)
        print(f"Compressed: {file} -> {output_file}")


args = parser.parse_args()

compress(f"{args.path}/static/javascript", "*.js")
compress(f"{args.path}/static/styles", "*.css")
compress(f"{args.path}/static/", "*.html")
