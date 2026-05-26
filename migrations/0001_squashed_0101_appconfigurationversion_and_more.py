# pylint: skip-file


import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [('passive_data_kit', '0001_initial'), ('passive_data_kit', '0002_databundle'), ('passive_data_kit', '0003_auto_20160211_0223'), ('passive_data_kit', '0004_auto_20160224_2218'), ('passive_data_kit', '0005_auto_20160224_2239'), ('passive_data_kit', '0006_auto_20160224_2240'), ('passive_data_kit', '0007_datapoint_generator_identifier'), ('passive_data_kit', '0008_datapointvisualizations'), ('passive_data_kit', '0009_reportjob'), ('passive_data_kit', '0010_auto_20160319_2148'), ('passive_data_kit', '0011_auto_20160319_2158'), ('passive_data_kit', '0012_auto_20160319_2225'), ('passive_data_kit', '0013_datafile'), ('passive_data_kit', '0014_auto_20160812_0243'), ('passive_data_kit', '0015_datafile_identifier'), ('passive_data_kit', '0016_datapoint_secondary_identifier'), ('passive_data_kit', '0017_datasourcealert'), ('passive_data_kit', '0018_datasourcealert_updated'), ('passive_data_kit', '0019_datasourcealert_alert_level'), ('passive_data_kit', '0020_auto_20170731_1939'), ('passive_data_kit', '0021_auto_20170731_2011'), ('passive_data_kit', '0022_auto_20170731_2133'), ('passive_data_kit', '0023_auto_20170731_2137'), ('passive_data_kit', '0024_datasource_performance_metadata'), ('passive_data_kit', '0025_datasource_performance_metadata_updated'), ('passive_data_kit', '0026_dataservermetadata'), ('passive_data_kit', '0027_auto_20170824_1708'), ('passive_data_kit', '0028_auto_20170828_1939'), ('passive_data_kit', '0029_auto_20170829_0147'), ('passive_data_kit', '0030_auto_20170907_1503'), ('passive_data_kit', '0031_reportjobbatchrequest'), ('passive_data_kit', '0032_reportjobbatchrequest_started'), ('passive_data_kit', '0033_datapoint_user_agent'), ('passive_data_kit', '0034_auto_20180323_1450'), ('passive_data_kit', '0035_auto_20180323_1511'), ('passive_data_kit', '0036_datasourcegroup_suppress_alerts'), ('passive_data_kit', '0037_datasource_suppress_alerts'), ('passive_data_kit', '0038_auto_20180821_1414'), ('passive_data_kit', '0039_dataservermetadatum_last_updated'), ('passive_data_kit', '0040_auto_20181213_2144'), ('passive_data_kit', '0041_auto_20181213_2231'), ('passive_data_kit', '0040_auto_20181202_1131'), ('passive_data_kit', '0042_merge_20181213_1844'), ('passive_data_kit', '0040_auto_20181115_1100'), ('passive_data_kit', '0043_merge_20190105_1102'), ('passive_data_kit', '0044_dataserverapitoken'), ('passive_data_kit', '0045_auto_20190326_1308'), ('passive_data_kit', '0045_auto_20190225_1821'), ('passive_data_kit', '0046_merge_20190330_2353'), ('passive_data_kit', '0047_auto_20190405_1754'), ('passive_data_kit', '0048_auto_20190405_1831'), ('passive_data_kit', '0049_auto_20190405_1853'), ('passive_data_kit', '0050_datasourcereference'), ('passive_data_kit', '0051_datapoint_source_reference'), ('passive_data_kit', '0052_auto_20190408_0724'), ('passive_data_kit', '0053_reportdestination'), ('passive_data_kit', '0054_auto_20190520_0003'), ('passive_data_kit', '0055_auto_20190520_0011'), ('passive_data_kit', '0056_auto_20190520_0028'), ('passive_data_kit', '0057_databundle_encrypted'), ('passive_data_kit', '0058_auto_20190609_1107'), ('passive_data_kit', '0059_auto_20190614_1335'), ('passive_data_kit', '0060_auto_20190620_2326'), ('passive_data_kit', '0061_databundle_compression'), ('passive_data_kit', '0062_auto_20190805_1550'), ('passive_data_kit', '0063_auto_20190806_1245'), ('passive_data_kit', '0064_auto_20190820_1437'), ('passive_data_kit', '0065_devicemodel_reference'), ('passive_data_kit', '0066_auto_20190820_1448'), ('passive_data_kit', '0067_auto_20190820_1503'), ('passive_data_kit', '0068_remove_deviceissue_platform_version'), ('passive_data_kit', '0069_auto_20190915_1605'), ('passive_data_kit', '0070_auto_20190915_1732'), ('passive_data_kit', '0071_auto_20190915_1939'), ('passive_data_kit', '0072_auto_20190922_1202'), ('passive_data_kit', '0073_dataserver_request_key'), ('passive_data_kit', '0074_auto_20191030_0902'), ('passive_data_kit', '0075_auto_20191115_1628'), ('passive_data_kit', '0076_deviceissue_tags'), ('passive_data_kit', '0077_deviceissue_device_model'), ('passive_data_kit', '0078_auto_20191126_1448'), ('passive_data_kit', '0079_databundle_errored'), ('passive_data_kit', '0080_auto_20200221_1241'), ('passive_data_kit', '0081_auto_20200227_0918'), ('passive_data_kit', '0082_auto_20200324_1646'), ('passive_data_kit', '0083_auto_20200324_1853'), ('passive_data_kit', '0084_auto_20200327_1118'), ('passive_data_kit', '0085_auto_20200327_1354'), ('passive_data_kit', '0086_auto_20200416_2210'), ('passive_data_kit', '0087_auto_20200419_1654'), ('passive_data_kit', '0088_auto_20200419_1705'), ('passive_data_kit', '0086_auto_20200416_1237'), ('passive_data_kit', '0089_merge_20200420_2124'), ('passive_data_kit', '0090_auto_20200420_2124'), ('passive_data_kit', '0091_auto_20200918_1819'), ('passive_data_kit', '0092_permissionssupport'), ('passive_data_kit', '0093_alter_datapoint_index_together'), ('passive_data_kit', '0094_auto_20230221_1840'), ('passive_data_kit', '0094_alter_datafile_data_point'), ('passive_data_kit', '0095_merge_20230307_2314'), ('passive_data_kit', '0096_datasource_configuration'), ('passive_data_kit', '0097_alter_appconfiguration_options'), ('passive_data_kit', '0098_alter_appconfiguration_configuration_json_and_more'), ('passive_data_kit', '0097_auto_20241030_1410'), ('passive_data_kit', '0099_merge_20241120_1548'), ('passive_data_kit', '0100_alter_appconfiguration_configuration_json_and_more'), ('passive_data_kit', '0101_appconfigurationversion_and_more')]

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DataBundle',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recorded', models.DateTimeField()),
                ('properties', models.TextField(max_length=34359738368)),
                ('processed', models.BooleanField(db_index=True, default=False)),
                ('encrypted', models.BooleanField(default=False)),
                ('compression', models.CharField(choices=[('none', 'None'), ('gzip', 'Gzip')], default='none', max_length=128)),
                ('errored', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='DataSourceGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=1024)),
                ('suppress_alerts', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='DataSource',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identifier', models.CharField(db_index=True, max_length=1024)),
                ('name', models.CharField(db_index=True, max_length=1024, unique=True)),
                ('group', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sources', to='passive_data_kit.datasourcegroup')),
                ('performance_metadata', models.JSONField(blank=True, null=True)),
                ('performance_metadata_updated', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('suppress_alerts', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='DataPointVisualization',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(db_index=True, max_length=1024)),
                ('generator_identifier', models.CharField(db_index=True, max_length=1024)),
                ('last_updated', models.DateTimeField(db_index=True)),
            ],
        ),
        migrations.CreateModel(
            name='DataServerMetadatum',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(db_index=True, max_length=1024)),
                ('value', models.TextField(max_length=1048576)),
                ('last_updated', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name_plural': 'data server metadata',
            },
        ),
        migrations.CreateModel(
            name='DataServerApiToken',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(blank=True, max_length=1024, null=True)),
                ('expires', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pdk_api_tokens', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'data server API token',
                'verbose_name_plural': 'data server API tokens',
            },
        ),
        migrations.CreateModel(
            name='DataGeneratorDefinition',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('generator_identifier', models.CharField(max_length=1024)),
                ('name', models.CharField(max_length=1024)),
                ('description', models.TextField(blank=True, max_length=1048576, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='DataSourceReference',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=1024)),
            ],
        ),
        migrations.CreateModel(
            name='DataServerAccessRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_identifier', models.CharField(db_index=True, max_length=4096)),
                ('request_type', models.CharField(db_index=True, max_length=4096)),
                ('request_time', models.DateTimeField(db_index=True)),
                ('request_metadata', models.TextField(max_length=34359738368)),
                ('successful', models.BooleanField(db_index=True, default=True)),
            ],
        ),
        migrations.CreateModel(
            name='DataServerAccessRequestPending',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_identifier', models.CharField(max_length=4096)),
                ('request_type', models.CharField(max_length=4096)),
                ('request_time', models.DateTimeField()),
                ('request_metadata', models.TextField(max_length=34359738368)),
                ('successful', models.BooleanField(default=True)),
                ('processed', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='DeviceModel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model', models.CharField(max_length=1024, unique=True)),
                ('manufacturer', models.CharField(max_length=1024)),
                ('notes', models.TextField(blank=True, max_length=1048576, null=True)),
                ('reference', models.URLField(blank=True, max_length=1048576, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Device',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(blank=True, max_length=1048576, null=True)),
                ('notes', models.TextField(blank=True, max_length=1048576, null=True)),
                ('model', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='devices', to='passive_data_kit.devicemodel')),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='devices', to='passive_data_kit.datasource')),
            ],
        ),
        migrations.CreateModel(
            name='DataServer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=1024, unique=True)),
                ('upload_url', models.URLField(max_length=1024, unique=True)),
                ('source_metadata_url', models.URLField(blank=True, max_length=1024, null=True)),
                ('request_key', models.CharField(blank=True, default='', max_length=1024, null=True)),
            ],
        ),
        migrations.AddField(
            model_name='datasource',
            name='server',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sources', to='passive_data_kit.dataserver'),
        ),
        migrations.AlterField(
            model_name='datasource',
            name='group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sources', to='passive_data_kit.datasourcegroup'),
        ),
        migrations.CreateModel(
            name='DeviceIssue',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(choices=[('opened', 'Opened'), ('in-progress', 'In Progress'), ('resolved', 'Resolved'), ('wont-fix', "Won't Fix")], default='opened', max_length=1024)),
                ('created', models.DateTimeField()),
                ('last_updated', models.DateTimeField()),
                ('description', models.TextField(blank=True, max_length=1048576, null=True)),
                ('stability_related', models.BooleanField(default=False)),
                ('uptime_related', models.BooleanField(default=False)),
                ('responsiveness_related', models.BooleanField(default=False)),
                ('battery_use_related', models.BooleanField(default=False)),
                ('power_management_related', models.BooleanField(default=False)),
                ('data_volume_related', models.BooleanField(default=False)),
                ('data_quality_related', models.BooleanField(default=False)),
                ('bandwidth_related', models.BooleanField(default=False)),
                ('storage_related', models.BooleanField(default=False)),
                ('configuration_related', models.BooleanField(default=False)),
                ('location_related', models.BooleanField(default=False)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='issues', to='passive_data_kit.device')),
                ('platform', models.CharField(blank=True, max_length=1048576, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=1048576, null=True)),
                ('app', models.CharField(blank=True, max_length=1048576, null=True)),
                ('correctness_related', models.BooleanField(default=False)),
                ('version', models.CharField(blank=True, max_length=1048576, null=True)),
                ('tags', models.CharField(blank=True, max_length=1048576, null=True)),
                ('device_model', models.CharField(blank=True, max_length=1048576, null=True)),
                ('device_performance_related', models.BooleanField(default=False)),
                ('device_stability_related', models.BooleanField(default=False)),
                ('ui_related', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='AppConfiguration',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=1024)),
                ('id_pattern', models.CharField(db_index=True, max_length=1024)),
                ('context_pattern', models.CharField(db_index=True, default='.*', max_length=1024)),
                ('configuration_json', models.JSONField()),
                ('evaluate_order', models.IntegerField(default=1)),
                ('is_valid', models.BooleanField(default=False)),
                ('is_enabled', models.BooleanField(default=True)),
            ],
            options={
                'index_together': {('is_valid', 'is_enabled'), ('is_valid', 'is_enabled', 'evaluate_order')},
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='DataPoint',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=1024)),
                ('generator', models.CharField(max_length=1024)),
                ('created', models.DateTimeField(db_index=True)),
                ('generated_at', django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ('recorded', models.DateTimeField(db_index=True)),
                ('properties', models.TextField(max_length=34359738368)),
                ('generator_identifier', models.CharField(db_index=True, default='unknown-generator', max_length=1024)),
                ('secondary_identifier', models.CharField(blank=True, max_length=1024, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=1024, null=True)),
                ('server_generated', models.BooleanField(db_index=True, default=False)),
                ('generator_definition', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='data_points', to='passive_data_kit.datageneratordefinition')),
                ('source_reference', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='data_points', to='passive_data_kit.datasourcereference')),
            ],
            options={
                'index_together': {('created', 'source_reference'), ('recorded', 'generator_definition')},
            },
        ),
        migrations.CreateModel(
            name='PermissionsSupport',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'permissions': (('passive_data_kit_dashboard_access', 'Access Passive Data Kit dashboard'), ('passive_data_kit_export_access', 'Create Passive Data Kit data exports')),
                'managed': False,
                'default_permissions': (),
            },
        ),
        migrations.CreateModel(
            name='DataFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_type', models.CharField(db_index=True, max_length=256)),
                ('content_file', models.FileField(upload_to='data_files')),
                ('data_point', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='data_files', to='passive_data_kit.datapoint')),
                ('data_bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='data_files', to='passive_data_kit.databundle')),
                ('identifier', models.CharField(db_index=True, default='', max_length=256)),
            ],
        ),
        migrations.AddField(
            model_name='datasource',
            name='configuration',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sources', to='passive_data_kit.appconfiguration'),
        ),
        migrations.AlterField(
            model_name='datasource',
            name='performance_metadata',
            field=models.TextField(blank=True, max_length=34359738368, null=True),
        ),
        migrations.CreateModel(
            name='DataSourceAlert',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_name', models.CharField(max_length=1024)),
                ('alert_details', models.TextField(max_length=34359738368)),
                ('generator_identifier', models.CharField(blank=True, max_length=1024, null=True)),
                ('created', models.DateTimeField(db_index=True)),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('data_source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='passive_data_kit.datasource')),
                ('updated', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('alert_level', models.CharField(choices=[('info', 'Informative'), ('warning', 'Warning'), ('critical', 'Critical')], db_index=True, default='info', max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name='ReportDestination',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('destination', models.CharField(max_length=4096)),
                ('description', models.CharField(blank=True, max_length=4096, null=True)),
                ('parameters', models.TextField(max_length=34359738368)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pdk_report_destinations', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ReportJob',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested', models.DateTimeField(db_index=True)),
                ('started', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('completed', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('parameters', models.TextField(max_length=34359738368)),
                ('report', models.FileField(blank=True, null=True, upload_to='pdk_reports')),
                ('requester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('sequence_count', models.IntegerField(default=1)),
                ('sequence_index', models.IntegerField(default=1)),
                ('priority', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='ReportJobBatchRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested', models.DateTimeField(db_index=True)),
                ('completed', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('parameters', models.TextField(max_length=34359738368)),
                ('requester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('started', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('priority', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='AppConfigurationVersion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=1024)),
                ('id_pattern', models.CharField(db_index=True, max_length=1024)),
                ('context_pattern', models.CharField(db_index=True, default='.*', max_length=1024)),
                ('configuration_json', models.JSONField()),
                ('evaluate_order', models.IntegerField(default=1)),
                ('is_valid', models.BooleanField(default=False)),
                ('is_enabled', models.BooleanField(default=True)),
                ('created', models.DateTimeField(blank=True, null=True)),
                ('updated', models.DateTimeField(blank=True, null=True)),
                ('configuration', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='versions', to='passive_data_kit.appconfiguration')),
                ('creator', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated'],
            },
        ),
    ]
