#! /bin/bash

function kill_pid () {
    pid=$1
    program="$2"

    echo "Killing $program with pid: $pid"
    kill $1
    if [ $? -ne 0 ]; then
        echo "Failed to kill $program with pid: $pid"
    else
        echo "Successfully killed $program with pid: $pid"
    fi
}

python -m src.scripts.run_query --query-data --only-for-update &
run_query_pid=$!

python -m src.scripts.store_update_history &
store_update_history_pid=$!

python -m src.utils.save_plots_and_table --only-for-update &
save_plots_and_table_pid=$!

python -m src.utils.update_model_bases --apply-all-corrections &
update_model_bases_pid=$!

python -m src.api.start_uvicorn &
uvicorn_pid=$!

streamlit run deploy_streamlit_app.py &
streamlit_app_pid=$!

wait $streamlit_app_pid

kill_pid $uvicorn_pid "Uvicorn (API server)"
kill_pid $run_query_pid "run_query.py"
kill_pid $store_update_history_pid "store_update_history.py"
kill_pid $save_plots_and_table_pid "save_plots_and_table.py"
kill_pid $update_model_bases_pid "update_model_bases.py"
kill_pid $streamlit_app_pid "Streamlit app"
