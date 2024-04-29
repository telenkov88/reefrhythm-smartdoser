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


def replace_lines_in_file(file_path, replacements):
    # Read the contents of the file
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Replace lines as specified in the replacements dictionary
    new_lines = []
    for line in lines:
        for old, new in replacements.items():
            if old in line:
                line = new
        new_lines.append(line)

    # Write the modified content back to the file
    with open(file_path, 'w', encoding='utf-8') as file:
        file.writelines(new_lines)

replacements = {
    'bootstrap.min.css':
    '    <link rel="stylesheet" href="styles/bootstrap.min.css">'+os.linesep,
    'bootstrap.bundle.min.js':
    '    <script src="javascript/bootstrap.bundle.min.js"></script>'+os.linesep
}


args = parser.parse_args()


shutil.copy(f"{args.path}/static/settings.html", f"{args.path}/static/settings-captive.html")
replace_lines_in_file(f"{args.path}/static/settings-captive.html", replacements)
compress(f"{args.path}/static/javascript", "*.js")
compress(f"{args.path}/static/styles", "*.css")
compress(f"{args.path}/static/", "*.html")
