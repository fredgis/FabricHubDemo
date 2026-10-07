"""Embedded in Fabric notebooks by build.py; uses their built-in Spark session."""
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse


def onelake_host(endpoint):
    parsed = urlparse(endpoint if "://" in endpoint else "https://" + endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".fabric.microsoft.com"):
        raise ValueError("Notebook context returned an invalid OneLake endpoint")
    return parsed.hostname


def bootstrap_raw(spark):
    spark.sql("CREATE SCHEMA IF NOT EXISTS raw")
    spark.sql("""CREATE TABLE IF NOT EXISTS raw.events_ingress (
        event_id STRING, event_type STRING, schema_version BIGINT,
        entity_key STRING, source_sequence BIGINT, occurred_at STRING,
        produced_at STRING, run_id STRING, correlation_id STRING, payload STRING
    ) USING DELTA""")
    spark.sql("""CREATE TABLE IF NOT EXISTS raw.reference_snapshots (
        record_id STRING, entity STRING, entity_key STRING, row_json STRING,
        run_id STRING, ingested_at TIMESTAMP, snapshot_complete BOOLEAN
    ) USING DELTA""")
    spark.sql("""CREATE TABLE IF NOT EXISTS raw.snapshot_batches (
        entity STRING, run_id STRING, ingested_at TIMESTAMP,
        snapshot_complete BOOLEAN, row_count BIGINT
    ) USING DELTA""")
    spark.sql("""CREATE TABLE IF NOT EXISTS raw.quarantine (
        record_id STRING, entity STRING, row_json STRING,
        reason STRING, run_id STRING, quarantined_at TIMESTAMP
    ) USING DELTA""")


def merge_rows(spark, table, frame, keys, condition=None):
    """Managed Delta only; replay-safe natural-key upsert."""
    from delta.tables import DeltaTable
    if not spark.catalog.tableExists(table):
        frame.write.format("delta").mode("overwrite").saveAsTable(table)
        spark.sql(f"ALTER TABLE {table} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
        return
    match = " AND ".join(f"t.`{k}` = s.`{k}`" for k in keys)
    merger = DeltaTable.forName(spark, table).alias("t").merge(frame.alias("s"), match)
    merger.whenMatchedUpdateAll(condition=condition).whenNotMatchedInsertAll().execute()


def quarantine(spark, table, frame):
    merge_rows(spark, table, frame, ["record_id"])


def eventhouse_delta_path(workspace_id, item_id, endpoint):
    uuid.UUID(workspace_id)
    uuid.UUID(item_id)
    return f"abfss://{workspace_id}@{onelake_host(endpoint)}/{item_id}/Tables/RawEvents"


def ingest_eventhouse_delta(spark, notebookutils, cfg):
    from delta.tables import DeltaTable
    from pyspark.sql import functions as F
    path = eventhouse_delta_path(
        notebookutils.runtime.context["currentWorkspaceId"],
        cfg["eventhouse_onelake_item_id"],
        notebookutils.conf.get("trident.onelake.endpoint"))
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    source = spark.read.format("delta").load(path)
    columns = spark.table("raw.events_ingress").columns
    missing = set(columns + ["payload_json"]) - set(source.columns)
    if missing:
        raise ValueError(f"Native Eventhouse Delta envelope columns missing: {sorted(missing)}")
    source = source.select(*[
        F.date_format(F.col(name), "yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'").alias(name)
        if name in ("occurred_at", "produced_at") else
        F.col("payload_json").alias("payload") if name == "payload" else F.col(name)
        for name in columns])
    source = source.withColumn("_hash", F.sha2(F.to_json(F.struct(*columns)), 256)).cache()
    try:
        count = source.count()
        if count > cfg.get("max_input_events", 100000):
            raise ValueError("Native Eventhouse Delta read exceeds the explicit input bound")
        if source.where("event_id IS NULL OR event_id = ''").limit(1).count():
            raise ValueError("Native Eventhouse Delta contains an event without an ID")
        if source.groupBy("event_id").agg(F.countDistinct("_hash").alias("variants")).where(
            "variants > 1").limit(1).count():
            raise ValueError("Native Eventhouse Delta has conflicting copies of an event ID")
        incoming = source.dropDuplicates(["event_id"])
        required = cfg.get("minimum_rti_events", 0)
        if incoming.count() < required:
            raise ValueError(f"Native OneLake history is incomplete; at least {required} event IDs required")
        existing = spark.table("raw.events_ingress").withColumn(
            "_hash", F.sha2(F.to_json(F.struct(*columns)), 256))
        conflicts = incoming.alias("s").join(existing.alias("t"), "event_id").where(
            F.col("s._hash") != F.col("t._hash"))
        if conflicts.limit(1).count():
            raise ValueError("Native Eventhouse event conflicts with persisted Raw; refusing overwrite")
        DeltaTable.forName(spark, "raw.events_ingress").alias("t").merge(
            incoming.drop("_hash").alias("s"), "t.event_id = s.event_id"
        ).whenNotMatchedInsertAll().execute()
        return {"source": "EventhouseOneLake", "source_rows": count,
                "distinct_events": incoming.count()}
    finally:
        source.unpersist()


def run_raw(spark, notebookutils, cfg, mode):
    from pyspark.sql import functions as F, types as T
    bootstrap_raw(spark)
    if mode == "bootstrap":
        return {"state": "raw_schema_ready", "events_observed": False}
    if mode != "ingest":
        raise ValueError("Raw mode must be bootstrap or ingest")
    if not cfg.get("run_id"):
        raise ValueError("run_id is required")
    if not all(name in cfg.get("sources", {}) for name in ("content", "customer")):
        raise ValueError("content/customer source paths are required; no synthetic source fallback")
    event_ingestion = None
    if cfg.get("rti_ingestion") == "eventhouse_onelake":
        event_ingestion = ingest_eventhouse_delta(spark, notebookutils, cfg)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    qschema = "record_id string, entity string, row_json string, reason string, run_id string, quarantined_at timestamp"
    result_schema = T.StructType([
        T.StructField("state", T.StringType()), T.StructField("key", T.StringType()),
        T.StructField("reason", T.StringType())])
    total_bad = 0
    for entity, source in cfg["sources"].items():
        if entity not in ENTITIES:
            raise ValueError(f"Unsupported reference entity: {entity}")
        if not source.get("path"):
            raise ValueError(f"sources.{entity}.path is required")
        if source.get("format", "json") not in ("json", "parquet", "delta"):
            raise ValueError("Source format must be json, parquet or delta")
        if source["path"].startswith(("http:", "https:")):
            raise ValueError("Stage public/source exports in OneLake Files; direct HTTP Spark reads are not ingress")
        if spark.table("raw.snapshot_batches").where(
            (F.col("entity") == entity) & (F.col("run_id") == cfg["run_id"])
        ).limit(1).count():
            continue
        reader = spark.read.format(source.get("format", "json"))
        if source.get("format", "json") == "json":
            reader = reader.option("multiline", str(source.get("multiline", True)).lower())
        rows = reader.load(source["path"])
        for original, target in source.get("column_mapping", {}).items():
            if target not in ENTITIES[entity]["fields"] or original not in rows.columns:
                raise ValueError(f"Invalid column_mapping for {entity}: {original} -> {target}")
            rows = rows.withColumnRenamed(original, target)
        if "_corrupt_record" in rows.columns and rows.where(F.col("_corrupt_record").isNotNull()).limit(1).count():
            raise ValueError(f"{entity}: malformed source JSON; batch was not marked complete")

        def normalize(text):
            try:
                state = validate_record(entity, json.loads(text))
                return canonical(state), state[ENTITIES[entity]["key"]], None
            except (ValueError, TypeError, KeyError) as exc:
                return None, None, str(exc)

        processed = rows.withColumn("_json", F.to_json(F.struct(*[F.col(c) for c in rows.columns])))
        processed = processed.withColumn("_result", F.udf(normalize, result_schema)("_json")).cache()
        bad = processed.where(F.col("_result.reason").isNotNull())
        count_bad = bad.count()
        total_bad += count_bad
        q = bad.select(F.sha2("_json", 256).alias("record_id"), F.lit(entity).alias("entity"),
                       F.col("_json").alias("row_json"), F.col("_result.reason").alias("reason"),
                       F.lit(cfg["run_id"]).alias("run_id"), F.lit(now).alias("quarantined_at"))
        quarantine(spark, "raw.quarantine", q)
        if count_bad > cfg.get("max_quarantine_records", 0):
            processed.unpersist()
            raise ValueError(f"{entity}: {count_bad} invalid source records quarantined; serving gate closed")
        valid = processed.where(F.col("_result.reason").isNull()).select(
            F.sha2(F.concat(F.lit(entity + ":" + cfg["run_id"] + ":"), "_json"), 256).alias("record_id"),
            F.lit(entity).alias("entity"), F.col("_result.key").alias("entity_key"),
            F.col("_result.state").alias("row_json"), F.lit(cfg["run_id"]).alias("run_id"),
            F.lit(now).alias("ingested_at"),
            # Never delete absent source records when any source record was rejected.
            F.lit(bool(source.get("snapshot_complete", False)) and count_bad == 0).alias("snapshot_complete"))
        if valid.groupBy("entity_key").count().where("count > 1").limit(1).count():
            raise ValueError(f"{entity}: duplicate natural keys in reference batch")
        count = valid.count()
        merge_rows(spark, "raw.reference_snapshots", valid, ["record_id"])
        batch = spark.createDataFrame([(entity, cfg["run_id"], now,
            bool(source.get("snapshot_complete", False)) and count_bad == 0, count)],
            "entity string, run_id string, ingested_at timestamp, snapshot_complete boolean, row_count long")
        merge_rows(spark, "raw.snapshot_batches", batch, ["entity", "run_id"])
        processed.unpersist()
    # Optional NDJSON replay / operational outbox export. This is real ingress,
    # never sample data; it must carry the identical envelope.
    if cfg.get("events_path"):
        source = spark.read.json(cfg["events_path"])
        if "_corrupt_record" in source.columns:
            raise ValueError("Malformed replay envelope JSON")
        payload_type = source.schema["payload"].dataType
        if isinstance(payload_type, (T.StructType, T.MapType)):
            source = source.withColumn("payload", F.to_json("payload"))
        source.select(*spark.table("raw.events_ingress").columns).write.format("delta").mode("append").saveAsTable("raw.events_ingress")
    return {"state": "raw_ingested", "quarantined": total_bad,
            "event_rows": spark.table("raw.events_ingress").count(), "run_id": cfg["run_id"],
            "event_ingestion": event_ingestion}


def run_silver(spark, notebookutils, cfg):
    from pyspark.sql import functions as F, types as T, Window
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.sql("CREATE SCHEMA IF NOT EXISTS silver")
    if not cfg.get("event_entity_map") or not cfg.get("run_id"):
        raise ValueError("event_entity_map and run_id are required")
    # Withdraw the serving gate before any writes. A failed run cannot leave the
    # previous success marker above a mixture of old and new managed tables.
    if spark.catalog.tableExists("silver.publication"):
        spark.sql("DELETE FROM silver.publication")
    workspace = notebookutils.runtime.context["currentWorkspaceId"]
    raw_id = cfg.get("raw_lakehouse_id")
    if not raw_id:
        raise ValueError("raw_lakehouse_id must be resolved during deployment")
    endpoint = onelake_host(notebookutils.conf.get("trident.onelake.endpoint"))
    raw_base = f"abfss://{workspace}@{endpoint}/{raw_id}/Tables/raw"
    events = spark.read.format("delta").load(raw_base + "/events_ingress")
    raw_count = events.count()
    if raw_count > cfg.get("max_input_events", 100000):
        raise ValueError("Bounded demo replay limit exceeded; compact/archive or raise explicitly")
    snapshots = spark.read.format("delta").load(raw_base + "/reference_snapshots")
    batches = spark.read.format("delta").load(raw_base + "/snapshot_batches")
    checked_schema = "entity string, entity_key string, state string, is_deleted boolean, reason string"

    def check(text):
        try:
            e = validate_event(json.loads(text), cfg["event_entity_map"], cfg.get("delete_event_types", []))
            if e["entity"] in ("rental", "offer") and not e["is_deleted"]:
                if e["payload"]["currency"] not in cfg.get("currency_exponents", {}):
                    raise ValueError("Currency exponent not configured")
            return e["entity"], e["entity_key"], canonical(e["payload"]), e["is_deleted"], None
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            return None, None, None, False, str(exc)

    events = events.withColumn("_json", F.to_json(F.struct(*[F.col(c) for c in events.columns])))
    events = events.withColumn("_hash", F.sha2("_json", 256))
    events = events.withColumn("_checked", F.udf(check, checked_schema)("_json")).cache()
    bad = events.where(F.col("_checked.reason").isNotNull())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    q = bad.select(F.col("_hash").alias("record_id"), F.lit("envelope").alias("entity"),
                   F.col("_json").alias("row_json"), F.col("_checked.reason").alias("reason"),
                   F.lit(cfg["run_id"]).alias("run_id"), F.lit(now).alias("quarantined_at"))
    quarantine(spark, "silver.quarantine", q)
    if bad.count() > cfg.get("max_quarantine_records", 0):
        raise ValueError("Invalid envelopes quarantined; Silver/Gold serving gate closed")
    good = events.where(F.col("_checked.reason").isNull())
    if good.groupBy("event_id").agg(F.countDistinct("_hash").alias("variants")).where("variants > 1").limit(1).count():
        raise ValueError("Conflicting event_id; no arbitrary winner")
    good = good.dropDuplicates(["event_id"]).select(
        "event_id", "source_sequence", "run_id", "occurred_at", "_hash",
        F.col("_checked.entity").alias("entity"), F.col("_checked.entity_key").alias("entity_key"),
        F.col("_checked.state").alias("row_json"), F.col("_checked.is_deleted").alias("is_deleted"))
    if good.groupBy("entity", "entity_key", "source_sequence").agg(
        F.countDistinct("_hash").alias("variants")
    ).where("variants > 1").limit(1).count():
        raise ValueError("Conflicting entity sequence; no arbitrary winner")
    latest_window = Window.partitionBy("entity_key").orderBy(F.desc("source_sequence"))
    for entity, spec in ENTITIES.items():
        schema = T.StructType([T.StructField(k, {
            "string": T.StringType(), "long": T.LongType(),
            "date": T.DateType(), "timestamp": T.TimestampType(), "boolean": T.BooleanType()
        }[kind]) for k, kind in spec["fields"].items()])
        # Partial reference snapshots upsert; the latest COMPLETE snapshot is an
        # explicit deletion boundary. No inferred CDC/delete from partial exports.
        entity_batches = batches.where(F.col("entity") == entity)
        complete = entity_batches.where("snapshot_complete").orderBy(F.desc("ingested_at")).limit(1).collect()
        reference = snapshots.where(F.col("entity") == entity)
        if complete:
            reference = reference.where(F.col("ingested_at") >= F.lit(complete[0]["ingested_at"]))
        rw = Window.partitionBy("entity_key").orderBy(F.desc("ingested_at"))
        reference = reference.withColumn("_rank", F.row_number().over(rw)).where("_rank = 1")
        reference = reference.select(
            "entity_key", "row_json", "run_id", F.lit(0).cast("long").alias("source_sequence"),
            F.lit(False).alias("is_deleted"), F.col("record_id").alias("event_id"),
            F.col("ingested_at").cast("string").alias("occurred_at"))
        if complete:
            # Persist complete-snapshot absence as tombstone rows as well as
            # removing it from the active serving table. Partial exports never
            # imply absence/delete.
            historic_keys = snapshots.where(F.col("entity") == entity).select("entity_key").distinct()
            missing = historic_keys.join(reference.select("entity_key"), "entity_key", "left_anti")
            deleted = missing.select(
                "entity_key",
                F.to_json(F.struct(F.col("entity_key").alias(spec["key"]))).alias("row_json"),
                F.lit(complete[0]["run_id"]).alias("run_id"),
                F.lit(0).cast("long").alias("source_sequence"),
                F.lit(True).alias("is_deleted"),
                F.sha2(F.concat(F.lit(entity + ":deleted:" + complete[0]["run_id"]), "entity_key"), 256).alias("event_id"),
                F.lit(complete[0]["ingested_at"]).cast("string").alias("occurred_at"))
            reference = reference.unionByName(deleted)
        live = good.where(F.col("entity") == entity).select(reference.columns)
        if entity in cfg.get("master_reference_entities", []):
            live = live.limit(0)
        combined = reference.unionByName(live)
        current = combined.withColumn("_rank", F.row_number().over(latest_window)).where("_rank = 1").drop("_rank")
        state = current.withColumn("_payload", F.from_json("row_json", schema, {
            "mode": "FAILFAST", "timestampFormat": "yyyy-MM-dd'T'HH:mm:ss[.SSSSSSSSS]XXX",
            "dateFormat": "yyyy-MM-dd",
        })).select(
            "_payload.*", "source_sequence", "is_deleted", "event_id", "run_id",
            F.to_timestamp("occurred_at").alias("last_event_at"))
        required_null = " OR ".join(f"`{name}` IS NULL" for name in spec["required"])
        if state.where(f"NOT is_deleted AND ({required_null})").limit(1).count():
            raise ValueError(f"{entity}: typed conversion lost a required value; publication blocked")
        # Full bounded replay preserves historical tombstones; missing input does
        # not resurrect them. Managed tables are required for ontology backing.
        state.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"silver.state_{entity}")
        active = state.where("NOT is_deleted").drop("is_deleted")
        active.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"silver.{entity}")
    # Materialize relation tables and fail closed on missing required endpoints.
    for name, (left, lkey, right, rkey, source) in LINKS.items():
        rows = spark.table(f"silver.{source}").select(lkey, rkey).where(
            F.col(lkey).isNotNull() & F.col(rkey).isNotNull()).dropDuplicates()
        a = spark.table(f"silver.{left}").select(lkey).dropDuplicates()
        b = spark.table(f"silver.{right}").select(rkey).dropDuplicates()
        orphan = rows.join(a, lkey, "left_anti").unionByName(rows.join(b, rkey, "left_anti")).dropDuplicates()
        if orphan.limit(1).count():
            orphan_q = orphan.select(
                F.sha2(F.to_json(F.struct(*[F.col(c) for c in orphan.columns])), 256).alias("record_id"),
                F.lit(name).alias("entity"), F.to_json(F.struct(*[F.col(c) for c in orphan.columns])).alias("row_json"),
                F.lit("unresolved relation endpoint").alias("reason"),
                F.lit(cfg["run_id"]).alias("run_id"), F.lit(now).alias("quarantined_at"))
            quarantine(spark, "silver.quarantine", orphan_q)
            raise ValueError(f"{name}: unresolved relation endpoint; Gold/ontology gate closed")
        rows.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"silver.link_{name}")
    # Territory is reference-derived, not a fabricated territory catalog.
    territories = spark.table("silver.customer").select("territory").unionByName(
        spark.table("silver.offer").select("territory")).where("territory IS NOT NULL").distinct()
    territories.write.format("delta").mode("overwrite").saveAsTable("silver.territory")
    # An explicit publication marker prevents a failed partial Silver run from
    # being loaded into Gold or newly bound into the ontology.
    marker = spark.createDataFrame([(cfg["run_id"], now, good.count(), raw_count)],
        "run_id string, completed_at timestamp, distinct_events long, raw_rows long")
    marker.write.format("delta").mode("overwrite").saveAsTable("silver.publication")
    events.unpersist()
    return {"state": "silver_published", "run_id": cfg["run_id"], "distinct_events": good.count()}
