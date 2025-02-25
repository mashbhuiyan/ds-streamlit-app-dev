'''
20241113 SW
This script should be run when it's time to write the local state bases db
to the main db
or read the latest live model from the main db (Note: reading overwrites any changes made locally)

input: path to local dbs, iterator for model_version (defaults to + 1), optional: model version iter breakdown,{model_id:iter} in case using different model iterators for different model ids
actions:
if the state base or any feature weight has changed, the model version is iterated
for state bases:
if a base is different, a new line is added for this state, old line has live marked false
if not, the end version is updated to the latest end version on existing lines
for feature weights:
if a weight has changed, new line is added
if not, but feature group and feature group type still exists in local with same weight, end version is iterated
else, line is marked live = 0
all new lines get created at assigned here, in future, created at should be assigned only when model goes live in production
output: .csv file with new model versions per model_id, written to path_to_local_dbs

'''


from datetime import datetime
import pandas as pd
import numpy as np
import sys,os,json, argparse
import psycopg2
import psycopg2.extras
from sshtunnel import SSHTunnelForwarder
from dotenv import load_dotenv



def load_env_variables(env_from_environment_info=False,use_staging_env=True):

    env_vars = {}
    if env_from_environment_info:
        #used by monitor
        # ds-mon-prod imports
        from src.environment.initialize_environment import environment_info

        env_vars["db_password"] = environment_info.DS_DB_PASSWORD.get_secret_value()
        env_vars["db_user"] = environment_info.DS_DB_USER.get_secret_value()
        #if monitor is run in staging model, DS_DB_NAME is already the staging db
        env_vars["db_name"] = environment_info.DS_DB_NAME.get_secret_value()
        env_vars["db_host"] = environment_info.DS_DB_HOST.get_secret_value()
        env_vars["ssh_host"] = environment_info.TUNNEL_REMOTE_HOST
        env_vars["ssh_user"] = environment_info.TUNNEL_USER
        env_vars["ssh_private_key_path"] = environment_info.TUNNEL_PRIVATE_KEY_PATH
    else:
        
        load_dotenv(dotenv_path='.env')
        env_vars["db_password"] = os.getenv("DS_DB_PASSWORD")
        env_vars["db_user"] = os.getenv("DS_DB_USER")
        if use_staging_env:
            env_vars["db_name"] = os.getenv("DS_DB_NAME_STAGE")
        else:
            env_vars["db_name"] = os.getenv("DS_DB_NAME")
        env_vars["db_host"] = os.getenv("DS_DB_HOST")
        env_vars["ssh_host"] = os.getenv("SSH_HOST")
        env_vars["ssh_user"] = os.getenv("SSH_USER")
        env_vars["ssh_private_key_path"] = os.getenv("SSH_PRIVATE_KEY_PATH")
    
    env_vars["local_port_address"] = 5432

    return env_vars

def write_new_model_to_main_db(local_db_path="../rtb_bid_generator/databases/",model_version_iter=1,\
                               model_version_breakdown=None,updated_by="NA",disable_user_input=False,\
                               use_staging_env=True,unblock_updates=False,env_from_environment_info=False):

    env_vars = load_env_variables(env_from_environment_info=env_from_environment_info,use_staging_env=use_staging_env)

    if unblock_updates:
        handle_blocking_updates_to_main_db(env_vars,block=False)
    
    local_state_db_file = local_db_path+"state_bases_local_db.csv"    
    local_state_db = pd.read_csv(local_state_db_file,index_col=[0])
    state_main_name = "anton_state_bases" 
    
    local_feature_db_file = local_db_path+"feature_weights_local_db.csv"    
    local_feature_db = pd.read_csv(local_feature_db_file,index_col=[0])
    feature_main_name = "anton_feature_weights" 
    
    model_ids = local_state_db["model_id"].unique()
    
    #sanity check
    if len(local_feature_db["model_id"].unique()) != len(model_ids):
        sys.exit("ERROR: the number of unique model ids is inconsistent between local and main")


    #Here I need to pull all live data from the main db.
    #Get the latest model version for each model_id
    #run sanity check that theres only one latest model version
    #For now we are writing for the first time
    main_state_db,main_feature_db = get_main_dbs(state_main_name,feature_main_name,env_vars,exit_if_blocked=True)
    model_versions = get_model_versions(main_state_db,main_feature_db)

    #if writing the table for the first time
#    main_state_db = pd.DataFrame(columns=["id","model_id","param_name","state_group","state_group_type","state","state_base","start_version","end_version","live","created_at"])
#    main_feature_db = pd.DataFrame(columns=["id","model_id","param_name","feature_group","feature_group_type","feature_weight","nd_combo","nfd_combo","flat_scaleup_factor","start_version","end_version","live","created_at"])
#    model_versions = {"auto":3013002,"home":1008002}


    print ("Live model_versions",model_versions)
    
    for model_id in model_ids:
        old_model_version = model_versions[model_id]
        new_model_version = None
        if model_version_breakdown is not None and model_id in model_version_breakdown:
            new_model_version = int(model_version_breakdown[model_id])
        else:
            new_model_version = int(old_model_version + model_version_iter)
        
        #From here on the logic should be the same for state and feature db, so call with generic model
        #don't update until after confirming that something has really changed
        state_base_updates = check_for_updates(local_state_db,main_state_db,model_id,new_model_version,updated_by)

        feature_weight_updates = check_for_updates(local_feature_db,main_feature_db,model_id,new_model_version,updated_by)

        print ("Updates check complete")
        print ("State",model_id)
        print ("Original n live rows",len(main_state_db.loc[main_state_db["model_id"] == model_id]))
        print ("New rows",len(state_base_updates["rows_to_insert"]["model_id"]))
        print ("Disabled rows",len(state_base_updates["live_0_ids"]))
        print ("Rows with version updated",len(state_base_updates["version_update_ids"]))
        print ("Feature weights")
        print ("Original n live rows",len(main_feature_db.loc[main_feature_db["model_id"] == model_id]))
        print ("New rows",len(feature_weight_updates["rows_to_insert"]["model_id"]))
        print ("Disabled rows",len(feature_weight_updates["live_0_ids"]))
        print ("Rows with version updated",len(feature_weight_updates["version_update_ids"]))


        if len(state_base_updates["live_0_ids"]) > 0 or len(feature_weight_updates["live_0_ids"]) > 0 or\
           len(state_base_updates["rows_to_insert"]["model_id"]) > 0 or len(feature_weight_updates["rows_to_insert"]["model_id"]) > 0:

            user_input = None
            if not disable_user_input:
                user_input = input("Enter '1' to write these changes to the main db: ")
            if disable_user_input or user_input == "1":
                #The model has been updated, need to apply all updates to main
                write_model_updates(state_base_updates,state_main_name,new_model_version,env_vars)
                write_model_updates(feature_weight_updates,feature_main_name,new_model_version,env_vars)
            else:
                print ("Updates not applied")
            
        else:
            print ("No updates to",model_id)

        #After the update, read the number of live events for this model id
        #confirm nlive is as expected, function does extra sanity checks
        #model_db = main_db.loc[(main_db["model_id"] == model_id)]
        #nlive_after_update,NA = get_nlive_and_model_version(model_db,new_model_version,after_update=True)
        #if nlive_after_update != nlive_expected:
        #    print ("ERROR: the number of live rows in the main db after update are not as expected",model_id,nlive_expected,nlive_after_update)

    return

def check_for_updates(local_db,main_db,model_id,new_model_version,updated_by):
    #get subset of main_db for this model_id with highest version number
    main_model_db = main_db.loc[(main_db["model_id"] == model_id)]
    local_model_db = local_db.loc[(local_db["model_id"] == model_id)]
    
    rows_to_insert,version_update_ids,live_0_ids,nlive_expected = get_rows_to_update_and_insert(local_model_db,main_model_db,model_id,new_model_version,updated_by)

    return {"rows_to_insert":rows_to_insert,"version_update_ids":version_update_ids,"live_0_ids":live_0_ids,"nlive_expected":nlive_expected}

               
def get_rows_to_update_and_insert(local_db,main_db,model_id,new_model_version,updated_by):

    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    #This generic model works for state base or feature weights
    state_bases = True if "state_group" in local_db.columns else False
               
    insert_all = False
    nlive=0
    if len(main_db) < 1:
        #if no main db entry for this model id, create new entries
        print ("No live entries in main db for this model_id, creating all new entries",model_id)
        insert_all = True
    else:
        #FIXME: do I need the model version here, don't think so
        nlive = get_nlive(main_db)

    rows_to_insert = {}
    for col in main_db.columns:
        if not col == "id":
            rows_to_insert[col] = []

    #these are rows where the value has not changed, so we need to update the end model_id
    version_update_ids = []
    #either rows which are disabled because the weight changed
    #or disabled before the feature group feature group type combo doesn't exist in the new model
    live_0_ids = []
        
    #loop over all model params, check for changes between local and main. If changed
    #for sanity check that nlive in db after change is as expected
    nlive_expected = nlive
    for local_index in local_db.index[local_db["model_id"] == model_id]:
        new_row = False
        if insert_all:
            nlive_expected += 1
            new_row=True
        else:
            #get the index for this param name, state group, state group type and state from main_db
            main_db_value = None
            local_db_value=None
            if state_bases:
                if len(main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                   (main_db["state_group"] == local_db.loc[local_index,"state_group"])]) == 0 or\
                    len(main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                    (main_db["state_group"] == local_db.loc[local_index,"state_group"]) & \
                                    (main_db["state_group_type"] == local_db.loc[local_index,"state_group_type"])]) == 0 or\
                    len(main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                    (main_db["state_group"] == local_db.loc[local_index,"state_group"]) & \
                                    (main_db["state_group_type"] == local_db.loc[local_index,"state_group_type"]) &\
                                    (main_db["state"] == local_db.loc[local_index,"state"])]) == 0:
                    print ("WARNING: Local db has new entry for state bases",local_db.loc[local_index,"state_group"],local_db.loc[local_index,"state_group_type"],\
                           local_db.loc[local_index,"state"])
                    
                    new_row=True
                    
                else:
                    main_db_value = main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                                (main_db["state_group"] == local_db.loc[local_index,"state_group"]) & \
                                                (main_db["state_group_type"] == local_db.loc[local_index,"state_group_type"]) &
                                                (main_db["state"] == local_db.loc[local_index,"state"]),"state_base"]
                    local_db_value = local_db.loc[local_index,"state_base"]
            else:
                if len(main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                             (main_db["feature_group"] == local_db.loc[local_index,"feature_group"])]) == 0 or\
                    len(main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                             (main_db["feature_group"] == local_db.loc[local_index,"feature_group"]) & \
                                             (main_db["feature_group_type"] == local_db.loc[local_index,"feature_group_type"])]) == 0:
                    new_row=True
                else:
                
                    main_db_value = main_db.loc[(main_db["param_name"] == local_db.loc[local_index,"param_name"]) & \
                                                 (main_db["feature_group"] == local_db.loc[local_index,"feature_group"]) & \
                                                 (main_db["feature_group_type"] == local_db.loc[local_index,"feature_group_type"]),"feature_weight"]
                    local_db_value = local_db.loc[local_index,"feature_weight"]
                    
            if not new_row:
                local_db_value = round_to_significant_digits(local_db_value,4)
                if len(main_db_value) > 1:
#                    breakpoint()
                    sys.exit("ERROR: main db has more than one match to this value")
                elif len(main_db_value) == 1:
                    if abs(main_db_value.iloc[0]-local_db_value)/main_db_value.iloc[0] > 0.005:
                        #> 0.5% difference relative to previous main db value
                        #The value needs to be updated
                        new_row=True
                        live_0_ids.append(main_db.loc[main_db_value.index[0],"id"])
                        #                        print ("Warning: new row for",end=" ")
                        #                        for col in local_db.columns:
                        #                            print (local_db.loc[index,col],end=" ")
                        #                        print (" old val",main_db_value.iloc[0])
                        #                        breakpoint()
                    else:
                        
#                        breakpoint()
                        #The value was not updated. Update the model version on the existing index
                        version_update_ids.append(main_db.loc[main_db_value.index[0],"id"])
                        #                    print ("Warning: keeping old row for")
                        #                    for col in local_db.columns:
                        #                        print (local_db.loc[local_index,col],end=" ")
                        #                    print ("")
            elif not new_row and len(main_db_value) == 0:
                #need to create new entries because no match in state group or state group type
                nlive_expected += 1
                new_row=True
                print ("Warning: new state group or state group type")
                for col_in in local_db.columns:
                    print (local_db.loc[local_index,col],end=" ")
                print ("")

        if new_row:
            for col in local_db.columns:
                if col != "created_at":
                    val = local_db.loc[local_index,col]
                    if col == "state_base" or col == "feature_weight":
                        val = round_to_significant_digits(val,4)
                    
                    rows_to_insert[col].append(val)
                    
            rows_to_insert["start_version"].append(new_model_version)
            rows_to_insert["end_version"].append(new_model_version)
            rows_to_insert["created_at"].append(current_time)
            rows_to_insert["updated_by"].append(updated_by)
            rows_to_insert["live"].append(True)

    for db_id in main_db["id"]:
        if not db_id in version_update_ids and not db_id in live_0_ids:
            #This should only happen for feature weights. It's when the feature group + feature group type no longer exists in the local db
            live_0_ids.append(db_id)
            
        
    return rows_to_insert,version_update_ids,live_0_ids,nlive_expected

def round_to_significant_digits(value, digits):
    if value == 0:
        return 0  
    return round(value, -int(f"{value:.1e}".split('e')[-1]) + (digits - 1))


def get_nlive(main_db,after_update=False):
    #Run sanity checks
    if len(main_db) < 1:
        sys.exit("ERROR: the model id exists, but there are no live entries, how is this possible? "+model_id)
    else:
        nlive = len(main_db)
        if len(main_db["end_version"].unique()) != 1:
            print (model_id,main_db["end_version"].unique())
            sys.exit("ERROR: there are multiple unique model end versions for this live model id, this should never happen")
#        else:
#            live_model_version = main_db["end_version"].unique()[0]
#            if (new_model_version <= live_model_version and not after_update) or (after_update and new_model_version != live_model_version):
#                print ('New model version',new_model_version,"live model version",live_model_version)
#                sys.exit("ERROR: the latest model version is <= the live model version")
#            if main_db["end_version"].max() > live_model_version or \
#               main_db["start_version"].max() > live_model_version:
#                sys.exit("ERROR: the max start or end version in the db is larger than the live model version")
    return nlive

def get_main_dbs(state_main_name,feature_main_name,env_vars,exit_if_blocked=True):

    with SSHTunnelForwarder(
            (env_vars["ssh_host"],22),
            ssh_username=env_vars["ssh_user"],
            ssh_private_key=env_vars["ssh_private_key_path"],
            remote_bind_address=(env_vars["db_host"],5432),
            local_bind_address=('localhost',env_vars["local_port_address"])) as tunnel:

        tunnel.start()

        conn = psycopg2.connect(
            host = tunnel.local_bind_host,
            database = env_vars["db_name"],
            user = env_vars["db_user"],
            password = env_vars["db_password"],
            port = tunnel.local_bind_port,
            connect_timeout=240)

        cursor = conn.cursor(cursor_factory = psycopg2.extras.RealDictCursor)
        print ("database connected",env_vars["db_name"])

        state_sql_query = "select * from "+state_main_name+" where live = true;"
        cursor.execute(state_sql_query)
        state_main_db = pd.DataFrame(cursor.fetchall())

        feature_sql_query = "select * from "+feature_main_name+" where live = true;"
        cursor.execute(feature_sql_query)
        feature_main_db = pd.DataFrame(cursor.fetchall())

        cursor.close()
        conn.close()

        if exit_if_blocked and state_main_db["block_updates"].max() == True:
            print ("ERROR: update blocked by block_updates. Exiting.")
            sys.exit(104)

    return state_main_db,feature_main_db


def write_model_updates(updates,table_name,new_model_version,env_vars):

    with SSHTunnelForwarder(
            (env_vars["ssh_host"],22),
            ssh_username=env_vars["ssh_user"],
            ssh_private_key=env_vars["ssh_private_key_path"],
            remote_bind_address=(env_vars["db_host"],5432),
            local_bind_address=('localhost',env_vars["local_port_address"])) as tunnel:


        tunnel.start()

        conn = psycopg2.connect(
            host = tunnel.local_bind_host,
            database = env_vars["db_name"],
            user = env_vars["db_user"],
            password = env_vars["db_password"],
            port = tunnel.local_bind_port,
            connect_timeout=240)

        cursor = conn.cursor()
        print ("Writing to db",env_vars["db_name"])
        
        
        if len(updates["live_0_ids"]) > 0:
            primary_keys = tuple([int(e) for e in updates["live_0_ids"]])
            update_query = "UPDATE "+table_name+" SET live = FALSE WHERE id IN %s;"

            cursor.execute(update_query,(primary_keys,))
            conn.commit()
            
            print (table_name,"live = false updated for",len(updates["live_0_ids"]),"rows")

        if len(updates["version_update_ids"]) > 0:
            primary_keys = tuple([int(e) for e in updates["version_update_ids"]])
            update_query = "UPDATE "+table_name+" SET end_version = "+str(new_model_version)+" WHERE id IN %s;"
            cursor.execute(update_query,(primary_keys,))
            conn.commit()
            
            print (table_name,"version updated for",len(updates["version_update_ids"]),"rows")
            
    
        if len(updates["rows_to_insert"]["model_id"]) > 0:
            #prep query to insert new rows
            insert_query = "INSERT INTO "+table_name+" ( "
            values_str = "VALUES ("
            for col in updates["rows_to_insert"]:
                if not col in ["block_updates","blocked_at"]:
                    insert_query += col+","
                    values_str += "%s,"
            insert_query = insert_query[:-1]+" ) "

            insert_query += values_str[:-1]+");"

            formatted_rows = []
            for rowi in range(len(updates["rows_to_insert"]["model_id"])):
                this_row = []
                for col in updates["rows_to_insert"]:
                    if not col in ["block_updates","blocked_at"]:
                        try:
                            this_row.append(updates["rows_to_insert"][col][rowi])
                        except:
                            print ("Fail")
                            breakpoint()
                formatted_rows.append(this_row)


            print ("Writing",len(updates["rows_to_insert"]["model_id"]),"new rows to",table_name)
            with conn:
                with conn.cursor() as cur:
                    cur.executemany(insert_query,formatted_rows)
            print (len(updates["rows_to_insert"]["model_id"]),"new rows successfully inserted into",table_name)
            

        cursor.close()
        conn.close()

    
    return 

def get_model_versions(main_state_db,main_feature_db):
    #get live model version per model id
    #run sanity checks
    model_versions = {}
    
    model_ids = main_state_db["model_id"].unique()
    cross_check_ids = main_feature_db["model_id"].unique()
    if len(model_ids) != len(cross_check_ids):
        print ("ERROR: different n model ids in state and feature dbs")
        sys.exit(102)

    for model_id in model_ids:
        if not model_id in cross_check_ids:
            print ("ERROR: different model ids in state and feature dbs")
            sys.exit(102)

        this_model_versions = main_state_db.loc[main_state_db["model_id"] == model_id,"end_version"].unique()
        if len(this_model_versions) != 1:
            print ("ERROR: != 1 model version for this model id",model_id,this_model_versions)
            sys.exit(102)
        elif main_feature_db.loc[main_feature_db["model_id"] == model_id,"end_version"].unique() != this_model_versions:
            feat_model_version = main_feature_db.loc[main_feature_db["model_id"] == model_id,"end_version"].unique()
            print ("ERROR: state and feature db model versions dont agree for this model id",model_id,this_model_versions,feat_model_version)
            sys.exit(102)
        else:
            model_versions[model_id] = this_model_versions[0]

    return model_versions


def read_live_model_from_main_db(local_db_path="../rtb_bid_generator/databases/",summarize_changes=False,use_staging_env=True,block_updates=False,env_from_environment_info=False):

    env_vars = load_env_variables(env_from_environment_info=env_from_environment_info,use_staging_env=use_staging_env)

    if block_updates:
        handle_blocking_updates_to_main_db(env_vars,block=True)

    local_state_db_file = local_db_path+"state_bases_local_db.csv"
    state_main_name = "anton_state_bases"

    local_feature_db_file = local_db_path+"feature_weights_local_db.csv"
    feature_main_name = "anton_feature_weights"

    versions_db_file = local_db_path+"model_versions.txt"
    current_model_versions = json.load(open(versions_db_file,"r"))

    
    main_state_db,main_feature_db = get_main_dbs(state_main_name,feature_main_name,env_vars,exit_if_blocked=False)
    main_model_versions = get_model_versions(main_state_db,main_feature_db)
    live_model_ids = main_state_db["model_id"].unique()
    
    for model_id in live_model_ids:
        main_model_versions[model_id] = int(main_model_versions[model_id])
    
    if summarize_changes:
        #This isn't necessary, it just created a summary of changes
        local_state_db = pd.read_csv(local_state_db_file,index_col=[0])
        local_feature_db = pd.read_csv(local_feature_db_file,index_col=[0])        

        for model_id in live_model_ids:
            main_model_versions[model_id] = int(main_model_versions[model_id])
            new_model_version = main_model_versions[model_id]
            local_model_version = -1
            if model_id in current_model_versions:
                #if the live model has the same model version, no update needed. local db will always be rewritten anyway
                local_model_version = current_model_versions[model_id]

            if local_model_version == new_model_version:
                print ("Note: Expect no change to model version in live db for",model_id,local_model_version)


            #even if the model version hasn't changed, still want to run the checks
            state_base_updates = check_for_updates(local_state_db,main_state_db,model_id,new_model_version+1)
            
            feature_weight_updates = check_for_updates(local_feature_db,main_feature_db,model_id,new_model_version+1)

            print ("Updates check complete",model_id,"new version",new_model_version)
            print ("State bases n live rows",len(main_state_db.loc[main_state_db["model_id"] == model_id]))
            print ("New rows",len(state_base_updates["rows_to_insert"]["model_id"]))
            print ("Feature weights n live rows",len(main_feature_db.loc[main_feature_db["model_id"] == model_id]))
            print ("new rows",len(feature_weight_updates["rows_to_insert"]["model_id"]))


    print ("Writing latest model to local db",local_state_db_file,local_feature_db_file,versions_db_file)
    fo = open(versions_db_file,"w")
    
    fo.write(json.dumps(main_model_versions))
    fo.close()

    main_state_db.set_index('id').sort_index().to_csv(local_state_db_file,\
                         columns=['model_id','param_name','state_group','state_group_type','state','state_base','created_at'])
    main_feature_db.set_index('id').sort_index().to_csv(local_feature_db_file,\
                           columns=['model_id','param_name','feature_group','feature_group_type','feature_weight','nd_combo','nfd_combo','flat_scaleup_factor','created_at'])

    
    return


def merge_live_model_from_main_db(local_db_path="../rtb_bid_generator/databases/",summarize_changes=False,\
                                  param_name=None,model_id=None,use_staging_env=True,env_from_environment_info=False):
    #Don't overwrite all local changes
    #Read the live model from main,
    #For the input model id and model parameter, take the feature weights and state bases from the local version only
    #merge the local weights and states bases for this model parameter, with the live main db model for all other parameters

    env_vars = load_env_variables(env_from_environment_info=env_from_environment_info,use_staging_env=use_staging_env)
    
    if param_name is None:
        print ("ERROR: param name to exclude from read is a required input")
        sys.exit(103)

    local_state_db_file = local_db_path+"state_bases_local_db.csv"
    state_main_name = "anton_state_bases"

    local_feature_db_file = local_db_path+"feature_weights_local_db.csv"
    feature_main_name = "anton_feature_weights"

    versions_db_file = local_db_path+"model_versions.txt"
    current_model_versions = json.load(open(versions_db_file,"r"))
    
    main_state_db,main_feature_db = get_main_dbs(state_main_name,feature_main_name,env_vars,exit_if_blocked=False)
    main_model_versions = get_model_versions(main_state_db,main_feature_db)
    live_model_ids = main_state_db["model_id"].unique()
    
    for model_id in live_model_ids:
        #for json dumps
        main_model_versions[model_id] = int(main_model_versions[model_id])

    #take the model_id + model_param data from local
    #exclude the model_id + model_param data from main
    #merge the data_frames
    local_state_db = pd.read_csv(local_state_db_file,index_col=[0])
    local_feature_db = pd.read_csv(local_feature_db_file,index_col=[0])        

    main_state_db = main_state_db.set_index('id').sort_index()
    main_feature_db = main_feature_db.set_index('id').sort_index()
    
    model_ids_to_merge = [model_id] if model_id is not None and model_id != 'all' else live_model_ids

    def merge_dbs_check_indices(db1,db2):
        common_indices = db1.index.intersection(db2.index)
        if not common_indices.empty:
            raise ValueError(f"Duplicate indices found: {common_indices.tolist()}")
        
        return pd.concat([db1,db2])
    
    def filter_db(db_to_concat,db_to_filter,model_id,param_name,option = None):
        #options: include/ exclude
        db_tmp = None
        if option == "include":
            db_tmp = db_to_filter.loc[(db_to_filter["model_id"] == model_id) &
                                      (db_to_filter["param_name"] == param_name)]
        elif option == "exclude":
            db_tmp = db_to_filter.loc[~((db_to_filter["model_id"] == model_id) &
                                        (db_to_filter["param_name"] == param_name))]
        else:
            sys.exit(103)
            
        if db_to_concat is None:
            db_to_concat = db_tmp
        else:
            db_to_concat = merge_dbs_check_indices(db_to_concat,db_tmp)

        return db_to_concat

    local_state_to_keep,local_feature_to_keep = None,None
    main_state_to_keep,main_feature_to_keep = None,None
    for model_id in model_ids_to_merge:
        local_state_to_keep = filter_db(local_state_to_keep,local_state_db,model_id,param_name,option="include")
        local_feature_to_keep = filter_db(local_feature_to_keep,local_feature_db,model_id,param_name,option="include")

        main_state_to_keep = filter_db(main_state_to_keep,main_state_db,model_id,param_name,option="exclude")
        main_feature_to_keep = filter_db(main_feature_to_keep,main_feature_db,model_id,param_name,option="exclude")

    merged_state_db = merge_dbs_check_indices(local_state_to_keep,main_state_to_keep)
    merged_feature_db = merge_dbs_check_indices(local_feature_to_keep,main_feature_to_keep)
        
    if summarize_changes:
        print ("Model merge complete for model_ids",model_ids_to_merge,"param_name",param_name)
        print ("States retained",len(local_state_to_keep.index),"from local",len(main_state_to_keep.index),"from main")
        print ("Feats retained",len(local_feature_to_keep.index),"from local",len(main_feature_to_keep.index),"from main")

        print ("Merged state db",len(merged_state_db.index))
        print ("Merged feature db",len(merged_feature_db.index))
        

    print ("Writing latest model to local db",local_state_db_file,local_feature_db_file,versions_db_file)
    fo = open(versions_db_file,"w")
    
    fo.write(json.dumps(main_model_versions))
    fo.close()

    merged_state_db.sort_index().to_csv(local_state_db_file,\
                         columns=['model_id','param_name','state_group','state_group_type','state','state_base','created_at'])
    merged_feature_db.sort_index().to_csv(local_feature_db_file,\
                           columns=['model_id','param_name','feature_group','feature_group_type','feature_weight','nd_combo','nfd_combo','flat_scaleup_factor','created_at'])

    
    return

def handle_blocking_updates_to_main_db(env_vars,block=True):
    #blocks if block=True
    #unblocks if block=False
    

    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    with SSHTunnelForwarder(
            (env_vars["ssh_host"],22),
            ssh_username=env_vars["ssh_user"],
            ssh_private_key=env_vars["ssh_private_key_path"],
            remote_bind_address=(env_vars["db_host"],5432),
            local_bind_address=('localhost',env_vars["local_port_address"])) as tunnel:


        tunnel.start()

        conn = psycopg2.connect(
            host = tunnel.local_bind_host,
            database = env_vars["db_name"],
            user = env_vars["db_user"],
            password = env_vars["db_password"],
            port = tunnel.local_bind_port,
            connect_timeout=240)

        cursor = conn.cursor()
        print ("Setting block_updates=",block," for live model in db",env_vars["db_name"])

        update_query=None
        if block:
            update_query = "UPDATE anton_state_bases SET block_updates=true, blocked_at='"+current_time+"' WHERE live=true;"
        else:
            update_query = "UPDATE anton_state_bases SET block_updates=false WHERE live=true;"
            
        cursor.execute(update_query)
        conn.commit()
            

        cursor.close()
        conn.close()

    return 

def get_config():
    parser = argparse.ArgumentParser(description="Select mode, environment, updated_by (mode w only), for the script.")

    parser.add_argument(
        "--mode", "-m",
        choices=["r","w","m","u","b"],
        type=str,
        default="r",
        help="Set the mode (r/w/m/u/b for read/write/merge/unblock updates/block updates). Default is 'r'."
    )

  
    parser.add_argument(
        "--env", "-e",
        choices=["staging", "production"],
        type=str,
        default="staging",
        help="Set the environment ('staging' or 'production'). Default is 'staging'."
    )

    parser.add_argument(
        "--updated_by", "-u",
        type=str,
        help="Who is making the update. Required in mode:w"
    )

    

    #execution will halt here with exit code 2 if invalid input provided
    args = parser.parse_args()

    if args.mode == "w" and not args.updated_by:
        print ("ERROR: --updated_by is a required arguments when --mode is 'w'.")
        sys.exit(1)

    
    return args



if __name__ == '__main__':
    config = get_config()

    mode = config.mode
    use_staging_env = True
    if config.env == "production":
        use_staging_env = False

    local_db_path = "../rtb_bid_generator/databases/"
    if mode == 'u':
        handle_blocking_updates_to_main_db(use_staging_env=use_staging_env,block=False)
        sys.exit(0)
    
    elif mode == 'w':
        updated_by = config.updated_by
        model_version_iter = 1
        model_version_breakdown = None
        write_new_model_to_main_db(local_db_path=local_db_path,model_version_iter=model_version_iter,\
                                   model_version_breakdown=model_version_breakdown,updated_by=updated_by,
                                   use_staging_env=use_staging_env)
        print ("Using mode",mode,"with updated_by",updated_by)
        sys.exit(0)

    elif mode == 'm':
        #using defaults for model id and param name
        model_id = "auto" if not "model_id" in body else body["model_id"]
        param_name = "nz_rev_click" if not "param_name" in body else body["param_name"]
        merge_live_model_from_main_db(local_db_path=local_db_path,model_id=model_id,param_name=param_name,use_staging_env=use_staging_env)
        sys.exit(0)
    elif mode == 'r':
        read_live_model_from_main_db(local_db_path=local_db_path,use_staging_env=use_staging_env)
        sys.exit(0)
    elif mode == 'b':
        handle_blocking_updates_to_main_db(use_staging_env=use_staging_env,block=True)
        sys.exit(0)

        


