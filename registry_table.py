import os
import synapseclient
# from synapseclient import Synapse
from synapseclient import  build_table, Column, Schema, Table #, Project, File, Folder, Row, RowSet, as_table_columns,
from synapseclient.core.exceptions import SynapseAuthenticationError, SynapseNoCredentialsError
import pandas as pd
import numpy as np
from dotenv import load_dotenv
load_dotenv('env/.env')
AUTH_TOKEN = os.getenv('SYNAPSE_AUTH_TOKEN')
PROJECT_ID = os.getenv('SYNAPSE_PROJECT_ID')

SRC_TABLES = {
    'dst': {        # convention in code, this abbreviation will be referred to as ..._tbl
                    #   ..._table will usually refer to some kind of table object
        'id': 'syn63096833', 'name': 'DataStandardOrTool',
    },
    'topic': {
        'id': 'syn63096835', 'name': 'DataTopic',
    },
    'org': {
        'id': 'syn63096836', 'name': 'Organization',
    },
    # 'uc': { 'id': 'syn63096837', 'name': 'UseCase', }
    # 'substr': { 'id': 'syn63096834', 'name': 'DataSubstrate', }
}
DEST_TABLES = {
    'DST_denormalized': {
        'dest_table_name': 'DST_denormalized',
        'base_table': 'dst',
        'columns': [
            # {'faceted': False, 'name': 'id',                        'alias': 'DST_ID'},
            {'faceted': False, 'name': 'name',                      'alias': 'Acronym'},
            {'faceted': False, 'name': 'description',               'alias': 'Name'},
            {'faceted': False, 'name': 'category',                  'alias': 'Category'},
            {'faceted': False, 'name': 'purpose_detail',            'alias': 'Description'},
            {'faceted': False, 'name': 'collection',                'alias': 'Collections'},
            # {'faceted': False, 'name': 'concerns_data_topic',       'alias': 'Data_Topic_IDs'},
            # {'faceted': False, 'name': 'has_relevant_organization', 'alias': 'Organization_IDs'},
            {'faceted': True,  'name': 'is_open',                   'alias': 'Is_Open'},
            {'faceted': True,  'name': 'requires_registration',     'alias': 'Registration'},
            {'faceted': False, 'name': 'url',                       'alias': 'URL'},
            {'faceted': False, 'name': 'formal_specification',      'alias': 'Formal_Spec'},
            {'faceted': False, 'name': 'publication',               'alias': 'Publication'},
            {'faceted': False, 'name': 'has_training_resource',     'alias': 'Training_Resources'},
            {'faceted': False, 'name': 'subclass_of',               'alias': 'Subclass_Of'},
            {'faceted': False, 'name': 'contribution_date',         'alias': 'Contribution_Date'},
            {'faceted': False, 'name': 'related_to',                'alias': 'Related_To'},
        ],
        # 'special_processing': dst_description_trim,
        'join_columns': [
            {'join_tbl': 'topic', 'join_type': 'left', 'from': 'concerns_data_topic', 'to': 'id',
             'dest_cols': [
                {'faceted': True, 'name': 'name', 'alias': 'Topic'},
                # {'faceted': False,'name': 'topics_json', 'alias': 'Topics',
                #  'fields': [{ 'name': 'name', 'alias': 'Topic'},
                #             { 'name': 'description', 'alias': 'Description'}, ]},
            ]},
            {'join_tbl': 'org', 'join_type': 'left', 'from': 'has_relevant_organization', 'to': 'id',
             'dest_cols': [
                 {'faceted': True,  'name': 'name', 'alias': 'Org_Acronym'},
                 {'faceted': True,  'name': 'description', 'alias': 'Org_Name'},
                 # {'faceted': False,  'name': 'orgs_json', 'alias': 'Organizations',
                 #  'fields': [{ 'name': 'name', 'alias': 'Acronym'},
                 #             { 'name': 'description', 'alias': 'Name'}, ]},
             ]}
        ],
    },
}

# def dst_description_trim(dst_table):
#     pass

def denormalize_tables():
    syn = initialize_synapse()
    src_tables = {tbl: get_src_table(syn, tbl) for tbl in SRC_TABLES}
    # project = syn.get(PROJECT_ID)
    for dest_table in DEST_TABLES.values():
        make_dest_table(syn, dest_table, src_tables)

def make_dest_table(syn, dest_table, src_tables):
    # get base table columns
    src_tbl = dest_table['base_table']
    dest_cols = [make_col(dest_table, dest_col, src_tables) for dest_col in dest_table['columns']]
    dest_cols = [col for col in dest_cols if col]  # get rid of empty -- haven't gotten json cols working yet
    for dest_col in dest_cols:
        src_table = src_tables[src_tbl]
        dest_col['data'] = src_table['df'][dest_col['name']] # values from this col in src_table

    # get join table columns
    base_table_name = dest_table['base_table']
    base_df = src_tables[base_table_name]['df']
    join_configs = dest_table.get('join_columns', [])

    join_columns = []

    for join_config in join_configs:
        join_tbl = join_config['join_tbl']
        join_table = src_tables[join_tbl]
        join_config['join_table_name'] = join_table['name']
        join_config['join_table_id'] = join_table['id']
        join_df = src_tables[join_tbl]['df']
        from_col = join_config['from']
        to_col = join_config['to']

        # Process each destination column specified in the join configuration
        for dest_col in join_config['dest_cols']:
            col_name = dest_col['alias']
            faceted = dest_col.get('faceted', False)

            if dest_col.get('fields'):
                # Handle JSON combined columns
                column_def = create_json_column(base_df, join_df, from_col, to_col, join_config, dest_col)
                if column_def:
                    join_columns.append(column_def)
            else:
                # Handle regular columns that contain lists of values
                column_def = create_list_column(base_df, join_df, from_col, to_col, join_config, dest_col)
                if column_def:
                    join_columns.append(column_def)
            column_def['faceted'] = faceted

    # Combine all columns (base + join) and create the destination table
    all_data = {col['alias']: col['data'] for col in dest_cols + join_columns if 'data' in col}
    all_data = pd.DataFrame(all_data)

    # Create the table schema
    all_dest_cols = [col for col in dest_cols + join_columns]
    for dest_col in all_dest_cols:
        col = dest_col['col']
        # Remove the column id so new column gets created
        col.pop('id', None)

        faceted = dest_col.get('faceted', False)
        if faceted:
            col['facetType'] = 'enumeration'

        if col['columnType'] == 'STRING_LIST':
            # Get the maximum number of items in the series of lists
            max_items = max(len(items) for items in all_data[col['name']])
            # Get the max string length in the all of the array of strings
            max_item_length = max(len(item) for items in all_data[col['name']] for item in items)
            col['maximumListLength'] = max_items + 2
            col['maximumSize'] = max_item_length + 10
            # The rationale for this is because if max size is set to 50 and max list length is 25, that is 50*25 bytes.
            # even if you don't store that much data.

    all_cols = [Column(**col['col']) for col in all_dest_cols]
    schema = Schema(name=dest_table['dest_table_name'], columns=all_cols, parent=PROJECT_ID)

    # Check if table already exists and delete all rows if it does
    try:
        existing_tables = syn.getChildren(PROJECT_ID, includeTypes=['table'])
        for table in existing_tables:
            if table['name'] == dest_table['dest_table_name']:
                # syn.delete(table['id']) I don't have permission to do this
                existing_rows = syn.tableQuery(f"select * from {table['id']}")
                print(f"Table {dest_table['dest_table_name']} already exists. Deleting {len(existing_rows)} rows.")
                syn.delete(existing_rows)
                break
    except Exception as e:
        print(f"Error checking for existing table: {str(e)}")

    # Create the table
    all_data = all_data.reset_index(drop=True)  # otherwise get error: Cannot update row: 16745 because it does not exist.
    table = syn.store(Table(schema, all_data))
    print(f"Created table: {table.schema.name} ({table.tableId})")


def create_list_column(base_df, join_df, from_col, to_col, join_config, dest_col):
    """
    Create a column containing lists of values from the joined table.

    For example, for each DST record, create a list of all related topic names.
    """
    field_name = dest_col['name']
    column_name = dest_col['alias']

    # Create a new column with lists of related values
    result = []

    for _, row in base_df.iterrows():
        related_ids = row[from_col]

        # Handle empty or missing relationships
        if not related_ids or (isinstance(related_ids, list) and len(related_ids) == 0):
            result.append([])
            continue

        # Ensure related_ids is a list
        if not isinstance(related_ids, list):
            related_ids = [related_ids]

        # Get all matching records from the join table
        matching_rows = join_df[join_df[to_col].isin(related_ids)]

        # Extract the requested field values
        field_values = matching_rows[field_name].tolist()
        result.append(field_values)

    # Create column definition and data
    column_def = {
        'src': join_config['join_table_name'],
        'name': field_name,
        'alias': column_name,
        'col': Column(name=column_name, columnType='STRING_LIST'),
        'data': result
    }

    return column_def


def create_json_column(base_df, join_df, from_col, to_col, join_config, dest_col):
    """
    Create a column containing JSON representations of related records.

    For example, for each DST record, create a list of JSON objects representing
    all related topics with their names and descriptions.
    """
    import json

    column_name = dest_col['alias']
    fields = dest_col['fields']

    # Create a new column with lists of JSON objects
    result = []

    for _, row in base_df.iterrows():
        related_ids = row[from_col]

        # Handle empty or missing relationships
        if not related_ids or (isinstance(related_ids, list) and len(related_ids) == 0):
            result.append("[]")
            continue

        # Ensure related_ids is a list
        if not isinstance(related_ids, list):
            related_ids = [related_ids]

        # Get all matching records from the join table
        matching_rows = join_df[join_df[to_col].isin(related_ids)]

        # Create JSON objects with the requested fields
        json_objects = []
        for _, related_row in matching_rows.iterrows():
            obj = {}
            for field in fields:
                field_name = field['name']
                field_alias = field.get('alias', field_name)
                obj[field_alias] = related_row[field_name]
            json_objects.append(obj)

        # Convert to JSON string
        # result.append(json.dumps(json_objects))
        # or not
        result.append(json_objects)

    # Create column definition and data
    column_def = {
        'src': join_config['join_table_name'],
        'name': join_config['join_tbl'],
        'alias': column_name,
        'col': Column(name=column_name, columnType='JSON'),
        'data': result
    }

    return column_def

def make_col(dest_table, dest_col, src_tables):
    faceted, name, alias = dest_col['faceted'], dest_col['name'], dest_col['alias']

    src_table = src_tables[dest_table['base_table']]
    dest_col['col'] = src_table['columns'][name].copy()
    dest_col['col']['name'] = dest_col['alias']

    # if faceted:   # don't know how to deal with facets yet
    # print(dest_col)
    return dest_col

def get_src_table(syn, tbl):
    table_info = SRC_TABLES[tbl]
    syn_table = syn.get(table_info['id'])
    if syn_table.name != table_info['name']:
        raise Exception(f'got wrong table for {table_info["name"]}: {syn_table.name}')
    table_info['syn_table'] = syn_table
    table_info['columns'] = {col['name']: col for col in syn.getTableColumns(syn_table)}

    data = syn.tableQuery(f"select * from {table_info['id']}")
    df = data.asDataFrame()
    # clean up nans
    for col in df.columns:
        df[col] = df[col].apply(lambda x: '' if isinstance(x, float) and np.isnan(x) else x)
    table_info['df'] = df
    return table_info

def initialize_synapse():
    try:
        syn = synapseclient.Synapse()
        syn.login(authToken=AUTH_TOKEN)
        return syn
    except (SynapseAuthenticationError, SynapseNoCredentialsError) as e:
        raise Exception(f"Failed to authenticate with Synapse: {str(e)}")

if __name__ == "__main__":
    denormalize_tables()

