"""Schema-only compatibility for genuinely empty, admitted SAP dimensions."""
from urllib.parse import urlparse


FIELDS = {
    "I_COSTCENTERACTIVITYTYPE": (
        ("CONTROLLINGAREA", "string"), ("COSTCTRACTIVITYTYPE", "string"),
        ("VALIDITYENDDATE", "date"), ("ACTIVITYTYPEISBLOCKED", "string"),
        ("ACTLPOSTGCOSTCENTERACTYTYPECAT", "string"),
        ("ACTUALPRICEALLOCATIONMETHOD", "string"),
        ("ACTUALQUANTITYISSETMANUALLY", "string"), ("ALLOCATIONCOSTELEMENT", "string"),
        ("COSTCTRACTIVITYTYPECATEGORY", "string"),
        ("COSTCTRACTIVITYTYPEOUTPQTYUNIT", "string"),
        ("COSTCTRACTIVITYTYPEQTYUNIT", "string"),
        ("COSTCTRACTIVITYTYPEVALIDCAT", "string"),
        ("COSTCTRACTYTYPEISCTRLGRLVTCOMP", "string"),
        ("COSTCTRACTYTYPEISHUMRSCERLVT", "string"), ("COSTORIGINGROUP", "string"),
        ("CREATIONDATE", "date"), ("ENTEREDBYUSER", "string"),
        ("FIXEDCOSTISPREDISTRIBUTED", "string"), ("OUTPUTQUANTITYFACTOR", "decimal(5,2)"),
        ("PERIODPRICEISAVERAGE", "string"), ("PLANQUANTITYISSETMANUALLY", "string"),
        ("PRICEALLOCATIONMETHOD", "string"), ("VALIDITYSTARTDATE", "date"),
    ),
    "I_COSTCENTERACTIVITYTYPETEXT": (
        ("VALIDITYENDDATE", "date"), ("CONTROLLINGAREA", "string"),
        ("COSTCTRACTIVITYTYPE", "string"), ("LANGUAGE", "string"),
        ("COSTCTRACTIVITYTYPENAME", "string"),
    ),
    "I_EQUIPMENT": (("EQUIPMENT", "string"),),
    "I_EQUIPMENTTEXT": (
        ("EQUIPMENT", "string"), ("LANGUAGE", "string"), ("EQUIPMENTNAME", "string"),
    ),
    "I_FIXEDASSET": (
        ("COMPANYCODE", "string"), ("FIXEDASSET", "string"), ("MASTERFIXEDASSET", "string"),
    ),
    "I_FUNCTIONALLOCATION": (("FUNCTIONALLOCATION", "string"),),
    "I_FUNCTIONALLOCATIONTEXT": (
        ("FUNCTIONALLOCATION", "string"), ("LANGUAGE", "string"),
        ("FUNCTIONALLOCATIONNAME", "string"),
    ),
    "I_PERSONWORKAGREEMENT_1": (
        ("PERSONWORKAGREEMENT", "string"), ("PERSON", "string"), ("PERSONFULLNAME", "string"),
    ),
    "I_PLANT": (("PLANT", "string"), ("PLANTNAME", "string")),
    "I_SHIPPINGPOINT": (("SHIPPINGPOINT", "string"),),
    "I_SHIPPINGPOINTTEXT": (
        ("LANGUAGE", "string"), ("SHIPPINGPOINT", "string"), ("SHIPPINGPOINTNAME", "string"),
    ),
    "I_WBSELEMENTDATA_2": (("WBSELEMENTINTERNALID", "int"),),
}


def field_names(spec):
    return tuple(name for name, _dtype in spec)


def expected_dtypes(spec):
    return {name: dtype for name, dtype in spec} | {
        "_SystemName": "string", "_UpdateTimeStamp": "timestamp", "_Delete": "string",
    }


def table_root(uri, workspace_id, item_id, schema):
    parsed = urlparse(uri)
    expected = f"/{workspace_id}/{item_id}/Tables"
    if (parsed.scheme != "https" or parsed.netloc != "onelake.dfs.fabric.microsoft.com"
            or parsed.path.rstrip("/") != expected or parsed.query or parsed.fragment or schema != "dbo"):
        raise ValueError("Empty-dimension recovery requires the exact discovered SAP OneLake coordinate")
    return f"abfss://{workspace_id}@{parsed.netloc}/{item_id}/Tables/{schema}"


def materialize(spark, notebookutils, config):
    from delta import DeltaTable
    from pyspark.sql import functions as F

    if config["source_system"] != "S4M" or set(config["fields"]) != set(FIELDS):
        raise ValueError("Recovery is limited to the twelve admitted, unused MSFlix SAP dimensions")
    actual_fields = {name: tuple(tuple(field) for field in spec)
                     for name, spec in config["fields"].items()}
    if actual_fields != FIELDS:
        raise ValueError("Empty source business columns or types changed")
    workspace = config["workspace_id"]
    mirror = table_root(config["mirror_path"], workspace, config["mirror_id"], config["mirror_schema"])
    silver = table_root(config["silver_path"], workspace, config["silver_id"], config["silver_schema"])
    context = notebookutils.runtime.context
    if context.get("defaultLakehouseId") != config["silver_id"]:
        raise ValueError("Recovery notebook must be bound to the dedicated native SAP Silver")
    results = {}
    for name, spec in FIELDS.items():
        fields = field_names(spec)
        source_path, target_path = mirror + "/" + name, silver + "/" + name
        if not DeltaTable.isDeltaTable(spark, source_path):
            raise ValueError(name + ": actual native mirrored source is not a valid Delta table")
        source = spark.read.format("delta").load(source_path)
        if not set(fields) <= set(source.columns):
            raise ValueError(name + ": actual mirrored business schema is incomplete")
        if source.limit(1).count() != 0:
            raise ValueError(name + ": source is not empty; native BPS processing is required")
        if DeltaTable.isDeltaTable(spark, target_path):
            target = spark.read.format("delta").load(target_path)
            if target.limit(1).count() != 0:
                raise ValueError(name + ": existing Silver contains rows; recovery must not modify it")
            if dict(target.dtypes) != expected_dtypes(spec):
                raise ValueError(name + ": existing empty Silver schema differs; overwrite is prohibited")
            results[name] = "unchanged_empty"
            continue
        if notebookutils.fs.exists(target_path):
            raise ValueError(name + ": non-Delta target exists; replacement is prohibited")
        empty = source.select(*(F.col(field).cast(dtype).alias(field)
                                for field, dtype in spec))
        empty = (empty.withColumn("_SystemName", F.lit(config["source_system"]).cast("string"))
                 .withColumn("_UpdateTimeStamp", F.lit(None).cast("timestamp"))
                 .withColumn("_Delete", F.lit(None).cast("string")))
        empty.write.format("delta").mode("errorifexists").save(target_path)
        actual = spark.read.format("delta").load(target_path)
        if actual.count() != 0 or not DeltaTable.isDeltaTable(spark, target_path):
            raise ValueError(name + ": schema-only recovery did not produce an empty Delta table")
        results[name] = "created_empty"
    return {"business_rows_written": 0, "gold_written": False, "tables": results}
