import json
import multiprocessing
import os
from pathlib import Path
from fhirclient.models.bundle import Bundle


def _verify_bundle(output_file_path) -> str:
    """Verify output file."""
    assert os.path.isfile(output_file_path), "Should be a file."
    bundle = Bundle(json.load(open(output_file_path)))
    assert bundle, "Should parse json into Bundle"
    # return a string so it can be serialized as across process boundaries
    return str(True)


def test_all_output_files(coherent_path, output_path, number_of_files_to_sample):
    """Ensure expected entities in output bundles."""
    fhir_path = Path(os.path.join(coherent_path, "output", "fhir"))
    assert os.path.isdir(fhir_path), "Input should exist"
    input_file_paths = list(fhir_path.glob('*.json'))
    assert len(input_file_paths) > 1200, "Should have over 1200 files."

    assert os.path.isdir(output_path), "Output should exist"
    output_path = Path(output_path)

    output_file_paths = list(output_path.glob('*.json'))
    assert len(input_file_paths) == len(output_file_paths), "Should have equal number of output files."

    if number_of_files_to_sample:
        output_file_paths = output_file_paths[:number_of_files_to_sample]

    pool_count = max(multiprocessing.cpu_count() - 1, 1)
    pool = multiprocessing.Pool(pool_count)
    results = pool.map(_verify_bundle, output_file_paths)
    assert all(results), "All files should be OK."


