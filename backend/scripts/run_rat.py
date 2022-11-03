import yaml
import os
import datetime
import argparse

import boto3

from core.run_vic import VICRunner
from utils.logging import init_logger, NOTIFICATION
from core.run_metsim import MetSimRunner
from core.run_routing import RoutingRunner
# from core.run_sarea import run_sarea
from core.run_postprocessing import run_postprocessing
# from core.run_altimetry import run_altimetry
from core.generate_plots import generate_plots

from utils.vic_param_reader import VICParameterFile
from utils.route_param_reader import RouteParameterFile
from utils.metsim_param_reader import MSParameterFile

# from data_processing.newdata import get_newdata
from data_processing.metsim_input_processing import generate_state_and_inputs
from data_processing.metsim_input_processing import ForcingsNCfmt
# from utils.temp_postprocessing import run_old_model, copy_generate_inflow, run_postprocess, publish
from utils.convert_for_website import convert_dels_outflow, convert_sarea, convert_inflow, convert_altimeter

def main():
    #------ Initialize Argument Parser ------#
    parser = argparse.ArgumentParser(description="Welcome to RAT-2.0")
    parser.add_argument('param_file', help='Absolute path to a rat-paramter file (format: yml)')
    args = parser.parse_args()
    param_path = args.param_file
    #------ Initialize Argument Parser ------#


    #--------- Define Variables -------------#
    # read parameter file
    config = yaml.safe_load(open(param_path, 'r'))

    # strip datetimes to remove the "time" component and only keep date
    config['GLOBAL']['begin'] = datetime.datetime.combine(config['GLOBAL']['begin'], datetime.time.min)
    config['GLOBAL']['end'] = datetime.datetime.combine(config['GLOBAL']['end'], datetime.time.min)
    config['GLOBAL']['previous_end'] = datetime.datetime.combine(config['GLOBAL']['previous_end'], datetime.time.min)
    #--------- Define Variables -------------#


    #--------- Initialize Log file ----------#
    log = init_logger(
        os.path.join(config['GLOBAL']['project_dir'], "backend/logs"),
        verbose=True,
        # notify=True,
        notify=False,
        log_level='DEBUG'
    )
    #--------- Initialize Log file ----------#


    # #--------- Download Data Begin ----------#
    # get_newdata(
    #     os.path.join(config['GLOBAL']['project_dir'], 'backend'),
    #     config['GLOBAL']['previous_end'],
    #     config['GLOBAL']['end']
    # )
    # #---------- Download Data End -----------#


    combined_datapath = os.path.join(config['GLOBAL']['project_dir'], 'backend', 'data', 'nc', 'combined_data.nc')
    # #----------- Process Data Begin -----------#
    # processed_datadir = os.path.join(config['GLOBAL']['project_dir'], 'backend', 'data', 'processed')
    # basingridfile = os.path.join(config['GLOBAL']['project_dir'], 'backend', 'data', 'ancillary', 'MASK.tif')
    # ForcingsNCfmt(
    #     config['GLOBAL']['previous_end'],
    #     config['GLOBAL']['end'],
    #     processed_datadir,
    #     basingridfile,
    #     combined_datapath,
    #     config['GLOBAL']['climatological_data']
    # )
    # #------------ Process Data End ------------#

    # download from s3
    s3 = boto3.client('s3')
    s3.download_file('saswe-meteorological-data', 'combined_data.nc', combined_datapath)

    #------ MetSim Data Processing Begin ------#
    # Process data to metsim format
    metsim_inputs_dir = os.path.join(config['GLOBAL']['project_dir'], 'backend', 'data', 'metsim_inputs')
    ms_state, ms_input_data = generate_state_and_inputs(
        config['GLOBAL']['previous_end'],
        config['GLOBAL']['end'],
        combined_datapath, 
        metsim_inputs_dir
    )
    #------- MetSim Data Processing End -------#


    #-------------- Metsim Begin --------------#
    with MSParameterFile(
        config['METSIM']['metsim_workspace'], 
        config['GLOBAL']['previous_end'],
        config['GLOBAL']['end'],
        config['METSIM']['metsim_param_file'], 
        ms_input_data, 
        ms_state
        ) as m:
        
        ms = MetSimRunner(
            m.ms_param_path,
            config['METSIM']['metsim_env'],
            config['GLOBAL']['conda_hook'],
            m.results,
            config['GLOBAL']['multiprocessing']
        )
        log.log(NOTIFICATION, f'Starting metsim from {config["GLOBAL"]["previous_end"].strftime("%Y-%m-%d")} to {config["GLOBAL"]["end"].strftime("%Y-%m-%d")}')
        ms.run_metsim()
        # # prefix = ms.diasgg_results(config['VIC']['vic_forcings_dir'])
        prefix = ms.convert_to_vic_forcings(config['VIC']['vic_forcings_dir'])
    #--------------- Metsim End ---------------#


    # --------------- VIC Begin ----------------# 
    with VICParameterFile(config) as p:
        vic = VICRunner(
            config['VIC']['vic_env'],
            p.vic_param_path,
            p.vic_result_file,
            None,            # Pass None as the route input directory, since we are not disaggregating the results   # config['ROUTING']['route_input_dir'], 
            config['GLOBAL']['conda_hook']
        )
        vic_result_fn = p.vic_result_file
        vic.run_vic(np=config['GLOBAL']['multiprocessing'])
        # vic.disagg_results()
        vic_startdate = p.vic_startdate
        vic_enddate = p.vic_enddate
    #---------------- VIC End -----------------#

    # upload to s3
    s3.upload_file(vic_result_fn, 'saswe-meteorological-data', 'vic_results.nc')

#     # vic_startdate = config['GLOBAL']['begin'] + datetime.timedelta(days=90)
#     # vic_enddate = config['GLOBAL']['end']
#     #------------- Routing Being --------------#
#     with RouteParameterFile(config, vic_startdate, vic_enddate, clean=False) as r:
#         route = RoutingRunner(    
#             config['GLOBAL']['project_dir'], 
#             r.params['output_dir'], 
#             # "extras/vic_cal_route_res/",
#             config['ROUTING']['route_inflow_dir'], 
#             config['ROUTING']['route_model'],
#             r.route_param_path, 
#             # 'extras/vic_cal_route_res/route_param.txt',
#             r.params['flow_direction_file'], 
#             config['ROUTING']['station_latlon_path'],
#             r.params['station']
#         )
#         route.create_station_file()
#         route.run_routing()
#         route.generate_inflow()
#     #-------------- Routing End ---------------#

#     #----------- Remote Sensing Begin -----------#
#     # Get Sarea
#     run_sarea("2019-01-01", config['GLOBAL']['end'].strftime("%Y-%m-%d"), os.path.join(config['GLOBAL']['project_dir'], "backend/data/sarea_tmsos"))

#     # Altimeter
#     run_altimetry("/houston2/pritam/rat_mekong_v3")
#     #----------- Remote Sensing End -----------#

#     #---------- Postprocessing Begin ----------#
#     run_postprocessing(config['GLOBAL']['project_dir'])

#     # Convert to format that is expected by the website
#     convert_sarea(config['GLOBAL']['project_dir'])
#     convert_inflow(config['GLOBAL']['project_dir'])
#     convert_dels_outflow(config['GLOBAL']['project_dir'])
#     convert_altimeter(config['GLOBAL']['project_dir'])
#     # ----------- Postprocessing End -----------#

#     # ---------- Create Visualization ----------#
#     generate_plots(config['GLOBAL']['reservoirs_db_fn'], config['GLOBAL']['project_dir'])
#     # ---------- Create Visualization ----------#

#     # Publish from .sh file


if __name__ == '__main__':
    main()