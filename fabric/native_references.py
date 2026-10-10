"""Canonical projections from the continuous Oracle mirror, shared by both ingress paths."""

ORACLE_QUERIES = {
    "content": """
        IF EXISTS (SELECT CONTENT_ID FROM DEMO_DW.REF_PRICE_RULE
                   GROUP BY CONTENT_ID HAVING COUNT(DISTINCT DISTRIBUTOR_ID)>1)
            THROW 51020, 'Multiple source distributors require an explicit rights model', 1;
        SELECT c.CONTENT_KEY AS content_key,c.TITLE AS title,
            CONVERT(varchar(10),c.RELEASE_DATE,23) AS release_date,
            c.DURATION_SECONDS AS duration_seconds,c.GENRE AS genre,c.IMAGE_URL AS image_url,
            c.SOURCE_URL AS source_url,c.LICENSE AS license,c.ATTRIBUTION AS attribution,
            d.DISTRIBUTOR_KEY AS distributor_key
        FROM DEMO_DW.REF_CONTENT c
        LEFT JOIN (SELECT CONTENT_ID,MAX(DISTRIBUTOR_ID) AS DISTRIBUTOR_ID
                   FROM DEMO_DW.REF_PRICE_RULE GROUP BY CONTENT_ID) p ON p.CONTENT_ID=c.CONTENT_ID
        LEFT JOIN DEMO_DW.REF_DISTRIBUTOR d ON d.DISTRIBUTOR_ID=p.DISTRIBUTOR_ID""",
    "offer": """
        SELECT p.PRICE_RULE_KEY AS offer_key,c.CONTENT_KEY AS content_key,
            t.TERRITORY_CODE AS territory,p.CURRENCY_CODE AS currency,
            CASE o.OFFER_TYPE WHEN 'RENTAL' THEN 'TVOD' WHEN 'PURCHASE' THEN 'EST' END AS transaction_type,
            p.AMOUNT_MINOR AS price_minor,o.START_WINDOW_HOURS AS start_window_hours,
            o.PLAY_WINDOW_HOURS AS play_window_hours
        FROM DEMO_DW.REF_PRICE_RULE p
        JOIN DEMO_DW.REF_CONTENT c ON c.CONTENT_ID=p.CONTENT_ID
        JOIN DEMO_DW.REF_OFFER o ON o.OFFER_ID=p.OFFER_ID
        JOIN DEMO_DW.REF_TERRITORY t ON t.TERRITORY_ID=p.TERRITORY_ID""",
    "distributor": """
        SELECT DISTRIBUTOR_KEY AS distributor_key,DISTRIBUTOR_NAME AS name
        FROM DEMO_DW.REF_DISTRIBUTOR""",
}

ORACLE_TABLES = {
    "content": ["DEMO_DW.REF_CONTENT", "DEMO_DW.REF_PRICE_RULE", "DEMO_DW.REF_DISTRIBUTOR"],
    "offer": ["DEMO_DW.REF_PRICE_RULE", "DEMO_DW.REF_CONTENT", "DEMO_DW.REF_OFFER", "DEMO_DW.REF_TERRITORY"],
    "distributor": ["DEMO_DW.REF_DISTRIBUTOR"],
}
