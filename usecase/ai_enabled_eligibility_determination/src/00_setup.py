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

spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}")

print(f"Schema  {catalog}.{schema} ready")
print(f"Volume  {catalog}.{schema}.{volume} ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

spark.sql(f"DESCRIBE SCHEMA {catalog}.{schema}").display()
