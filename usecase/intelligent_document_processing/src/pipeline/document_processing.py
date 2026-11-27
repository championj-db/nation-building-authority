# Lakeflow Spark Declarative Pipeline: the reusable document intelligence layer.
#
#   inbox volume --Auto Loader--> bronze_parsed_documents      ai_parse_document: text, tables, layout,
#                                                              bounding boxes, rendered page images
#                               -> silver_classified_documents ai_classify into a document type
#                               -> silver_invoice_extraction   ai_extract v2.1, per-field confidence + citations
#                               -> silver_statement_extraction
#                               -> silver_correspondence_extraction
#
# Every table is a streaming table, so each update only parses, classifies and extracts documents
# that arrived since the last one: AI functions run once per document, not once per refresh.
# The bronze layer is deliberately generic: other use cases can read bronze_parsed_documents without
# caring what this one does with invoices.
#
# Configuration (set by resources/document_pipeline.yml, nothing hard-coded):
#   idp.landing_path  /Volumes/<catalog>/<schema>/<volume>/inbox
#   idp.image_path    /Volumes/<catalog>/<schema>/<volume>/pages
#   idp.src_dir       the deployed src folder, so the shared schemas in common.py are used

import sys

import dlt
from pyspark.sql import functions as F

sys.path.insert(0, spark.conf.get("idp.src_dir"))

from common import (  # noqa: E402
    CORRESPONDENCE_SCHEMA,
    INVOICE_SCHEMA,
    INVOICE_TYPES,
    STATEMENT_SCHEMA,
    classify_labels_json,
    schema_json,
)

LANDING = spark.conf.get("idp.landing_path")
IMAGES = spark.conf.get("idp.image_path")


def sql_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


PARSE = f"ai_parse_document(content, map('version', '2.0', 'imageOutputPath', {sql_str(IMAGES)}, 'descriptionElementTypes', ''))"
CLASSIFY = (f"ai_classify(parsed, {sql_str(classify_labels_json())}, map('version', '2.0', 'instructions', "
            f"{sql_str('Documents received in the accounts payable inbox of an Australian Government entity.')}))")


def extract(schema: dict, instructions: str) -> str:
    return (f"ai_extract(parsed, {sql_str(schema_json(schema))}, map('version', '2.1', 'enableCitations', 'true', "
            f"'enableConfidenceScores', 'true', 'instructions', {sql_str(instructions)}))")


@dlt.table(
    name="bronze_parsed_documents",
    comment="Every document in the inbox volume, parsed once by ai_parse_document (v2.0): elements with type, text, "
            "bounding boxes and page images. Reusable bronze layer. Synthetic documents.",
    table_properties={"quality": "bronze"},
)
def bronze_parsed_documents():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .option("recursiveFileLookup", "true")
        .option("pathGlobFilter", "*.{pdf,PDF,jpg,jpeg,JPG,png,PNG}")
        .load(LANDING)
        .select(
            F.regexp_extract("path", r"/(DOC-\d+)_", 1).alias("doc_id"),
            F.col("path"),
            F.col("modificationTime").alias("file_modified_at"),
            F.col("length").alias("file_bytes"),
            F.sha2("content", 256).alias("content_sha256"),
            F.expr(PARSE).alias("parsed"),
            F.current_timestamp().alias("parsed_at"),
        )
    )


@dlt.table(
    name="silver_classified_documents",
    comment="Document type from ai_classify over the parsed document, with page images, page count and full text.",
    table_properties={"quality": "silver"},
)
@dlt.expect("parsed_without_error", "parse_error IS NULL")
def silver_classified_documents():
    return (
        dlt.read_stream("bronze_parsed_documents")
        .withColumn("classification", F.expr(CLASSIFY))
        .select(
            "doc_id", "path", "content_sha256", "parsed_at",
            F.expr("classification:response[0]::string").alias("doc_type"),
            F.expr("classification:error_message::string").alias("classify_error"),
            F.expr("size(cast(parsed:document:pages AS ARRAY<VARIANT>))").alias("page_count"),
            F.expr("transform(cast(parsed:document:pages AS ARRAY<VARIANT>), p -> p:image_uri::string)").alias("page_images"),
            F.expr("concat_ws('\\n', transform(cast(parsed:document:elements AS ARRAY<VARIANT>), e -> e:content::string))").alias("full_text"),
            # error_status is a VARIANT; a JSON null or an empty list both mean "parsed cleanly".
            F.expr("CASE WHEN to_json(parsed:error_status) IN ('null', '[]') OR parsed:error_status IS NULL THEN NULL "
                   "ELSE to_json(parsed:error_status) END").alias("parse_error"),
            F.col("parsed"),
        )
    )


def _extraction(types: tuple[str, ...], schema: dict, instructions: str):
    return (
        dlt.read_stream("silver_classified_documents")
        .where(F.col("doc_type").isin(*types))
        .withColumn("extraction", F.expr(extract(schema, instructions)))
        .select(
            "doc_id", "doc_type", "path", "parsed_at",
            F.expr("to_json(extraction:response)").alias("fields_json"),
            F.expr("to_json(extraction:metadata:citations)").alias("citations_json"),
            F.expr("to_json(parsed:document:elements)").alias("elements_json"),
            F.expr("extraction:error_message::string").alias("extract_error"),
            F.current_timestamp().alias("extracted_at"),
        )
    )


@dlt.table(name="silver_invoice_extraction", table_properties={"quality": "silver"},
           comment="Tax invoices and adjustment notes: typed fields from ai_extract v2.1, each with a confidence score and citations to bounding boxes on the page.")
def silver_invoice_extraction():
    return _extraction(INVOICE_TYPES, INVOICE_SCHEMA,
                       "Australian supplier tax invoice or adjustment note sent to an Australian Government entity. "
                       "Dates are Australian (day before month). Amounts are AUD. Return ABNs, BSBs and account numbers as digits only. "
                       "Leave a field empty when it is not printed on the document; never infer it.")


@dlt.table(name="silver_statement_extraction", table_properties={"quality": "silver"},
           comment="Supplier statements: balance, overdue amount and the invoice numbers listed, from ai_extract v2.1.")
def silver_statement_extraction():
    return _extraction(("supplier_statement",), STATEMENT_SCHEMA,
                       "Supplier statement of account sent to an Australian Government entity. Dates are Australian.")


@dlt.table(name="silver_correspondence_extraction", table_properties={"quality": "silver"},
           comment="Supplier correspondence: intent, referenced invoices and any new bank details, from ai_extract v2.1.")
def silver_correspondence_extraction():
    return _extraction(("correspondence",), CORRESPONDENCE_SCHEMA,
                       "Letter from a supplier to the accounts payable team of an Australian Government entity.")
