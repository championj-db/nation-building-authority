# Databricks notebook source
# MAGIC %md
# MAGIC # Setup — AI-Enabled Eligibility Determination
# MAGIC
# MAGIC Creates the schema, volume, and any prerequisite infrastructure for the use case.
# MAGIC All environment-specific values are parameterised — nothing is hard-coded.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"

print(f"catalog : {catalog}")
print(f"schema  : {schema}")
print(f"volume  : {volume}")

# COMMAND ----------

# The catalog is a pre-provisioned prerequisite supplied via the bundle `catalog` variable.
# Don't create it here: workspaces without a metastore storage root reject CREATE CATALOG.
assert spark.sql(f"SHOW CATALOGS LIKE '{catalog}'").count() == 1, (
    f"Catalog '{catalog}' not found or not accessible - create it first or set the `catalog` bundle variable"
)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}")

print(f"Schema  {catalog}.{schema} ready")
print(f"Volume  {catalog}.{schema}.{volume} ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

spark.sql(f"DESCRIBE SCHEMA {catalog}.{schema}").display()
