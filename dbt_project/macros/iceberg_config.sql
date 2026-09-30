{% macro iceberg_config(key, partitions=[]) %}
  {{ return({'materialized': 'incremental', 'incremental_strategy': 'merge',
             'unique_key': key, 'table_type': 'iceberg', 'format': 'parquet',
             'partitioned_by': partitions, 'write_compression': 'snappy'}) }}
{% endmacro %}
