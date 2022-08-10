import json

import click
import os
from pathlib import Path
import time
import multiprocessing
import logging
from fhirclient.models.bundle import Bundle, BundleEntry
from fhirclient.models.documentreference import DocumentReference
from fhirclient.models.specimen import Specimen
from fhirclient.models.task import Task, TaskInput, TaskOutput
from fhirclient.models.fhirreference import FHIRReference
from fhirclient.models.narrative import Narrative
import base64
import uuid
from itertools import repeat

logging.basicConfig(level=logging.DEBUG, format='%(process)d - %(name)s - %(levelname)s - %(message)s')


def _transform_bundle(file_path: Path, output_path: Path) -> dict:
    """Read json, update bundle with bundle Specimen, Task, ensure DocumentReference."""
    tic = time.perf_counter()
    bundle = Bundle(json.load(open(file_path)))
    diagnostic_reports = []
    document_references = []
    patient = None
    additional_entries = []
    conditions = []
    for e in bundle.entry:
        if e.resource.resource_type == 'Patient':
            patient = e.resource
        if e.resource.resource_type == 'DiagnosticReport':
            codes = [c.code for c in e.resource.code.coding]
            # genetic panel
            if '55232-3' in codes:
                diagnostic_reports.append(e.resource)
        if e.resource.resource_type == 'DocumentReference':
            data = base64.b64decode(e.resource.content[0].attachment.data).decode("utf-8")
            if "_dna.csv" in data:
                document_references.append(e.resource)
        if e.resource.resource_type == 'Condition':
            conditions.append(e.resource)

    output_file = None
    if len(diagnostic_reports) > 0:
        logging.info(f"{file_path} has {len(diagnostic_reports)} genetic analysis reports")
        for diagnostic_report in diagnostic_reports:
            # create a specimen
            specimen = Specimen()
            specimen.id = str(uuid.uuid5(uuid.UUID(diagnostic_report.id), 'specimen'))
            specimen.text = Narrative({"div": "Autogenerated specimen. Inserted to make data model research friendly.", "status": "generated"})
            specimen.subject = diagnostic_report.subject
            # add a reference to it back to the diagnostic report
            specimen_reference = FHIRReference({'reference': f"{specimen.resource_type}/{specimen.id}"})
            diagnostic_report.specimen = [specimen_reference]
            # add the specimen back to bundle
            additional_entries.append(specimen)
            # create a Task
            task = Task()
            task.id = str(uuid.uuid5(uuid.UUID(diagnostic_report.id), 'task'))
            task.text = Narrative({"div": "Autogenerated task. Inserted to make data model research friendly.", "status": "generated"})
            task.input = [TaskInput({'type': {'coding': [{'code': 'specimen'}]}, 'valueReference': specimen_reference.as_json()})]
            task.focus = specimen_reference
            task.output = [TaskOutput(
                {'type': {'coding': [{'code': diagnostic_report.resource_type}]},
                 'valueReference': {'reference': f"{diagnostic_report.resource_type}/{diagnostic_report.id}"}}
            )]
            assert len(
                document_references) == 1, "Should have found a document reference with a reference to the dna data."
            # this document reference is the clinical note
            document_reference = document_references[0]
            # clone the document reference, create new one with url
            document_reference_with_url = DocumentReference(document_reference.as_json())
            data = base64.b64decode(document_reference_with_url.content[0].attachment.data).decode("utf-8")
            lines = data.split('\n')
            line_with_file_info = next(
                iter([line for line in lines if 'genetic analysis summary panel  stored in' in line]), None)
            assert line_with_file_info
            path_from_report = line_with_file_info.split(' ')[-1]
            assert '_dna.csv' in path_from_report, f"{file_path}\n{data}\n{line_with_file_info}"
            # alter attachment
            document_reference_with_url.content[0].attachment.data = None
            document_reference_with_url.content[0].attachment.url = path_from_report
            additional_entries.append(document_reference_with_url)
            # unique id
            document_reference_with_url.id = str(uuid.uuid5(uuid.UUID(diagnostic_report.id), 'document_reference_with_url'))
            # add it to task
            task.output = [TaskOutput(
                {'type': {'coding': [{'code': document_reference_with_url.resource_type}]},
                 'valueReference': {'reference': f"{document_reference_with_url.resource_type}/{document_reference_with_url.id}"}}
            )]
            task.status = "completed"
            task.intent = "order"
            # add the task to bundle
            additional_entries.append(task)
        # add entries to bundle
        for additional_entry in additional_entries:
            bundle_entry = BundleEntry()
            bundle_entry.resource = additional_entry
            bundle.entry.append(bundle_entry)

    # write new bundle to output
    output_file = output_path.joinpath(file_path.name)
    json.dump(bundle.as_json(), open(output_file, "w"))

    toc = time.perf_counter()
    msg = f"Parsed {file_path} in {toc - tic:0.4f} seconds, wrote {output_file}"
    logging.getLogger(__name__).info(msg)
    return {
        'patient_id': patient.id,
        'conditions': [(condition.code.coding[0].code, condition.code.coding[0].display) for condition in conditions]
    }


@click.command()
@click.option('--coherent_path',
              default='coherent/',
              show_default=True,
              help='Path to unzipped coherent data - see http://hdx.mitre.org/downloads/coherent-08-10-2021.zip.')
@click.option('--output_path',
              default='output/',
              show_default=True,
              help='Path to output data.')
def transform(coherent_path, output_path):
    """Simple program re-writes synthea bundles."""
    assert os.path.isdir(coherent_path)
    assert os.path.isdir(output_path)
    output_path = Path(output_path)
    fhir_path = Path(os.path.join(coherent_path, "output", "fhir"))
    assert os.path.isdir(fhir_path)
    file_paths = list(fhir_path.glob('*.json'))
    assert len(file_paths) > 1200

    pool_count = max(multiprocessing.cpu_count() - 1, 1)
    pool = multiprocessing.Pool(pool_count)
    tic = time.perf_counter()
    # for patient_conditions in zip(*pool.map(_transform_bundle, file_paths)):
    for patient_conditions in pool.starmap(_transform_bundle, zip(file_paths, repeat(output_path))):
        # TODO - create ResearchStudy & ResearchSubject->Patient for each condition
        pass
    toc = time.perf_counter()
    msg = f"Parsed all files in {fhir_path} in {toc - tic:0.4f} seconds"
    logging.getLogger(__name__).info(msg)


if __name__ == '__main__':
    transform()
