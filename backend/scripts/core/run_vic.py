import pandas as pd
import rasterio as rio
import os
import xarray as xr
import numpy as np
from tqdm import tqdm
import csv
import time
import math

from logging import getLogger
from utils.logging import LOG_NAME, NOTIFICATION
from utils.utils import create_directory, run_command
from utils.vic_param_reader import VICParameterFile

log = getLogger(LOG_NAME)


class VICRunner():
    def __init__(self, vic_env, param_file, vic_result_file, rout_input_dir, conda_hook) -> None:
        self.vic_env = vic_env
        self.param_file = param_file
        self.vic_result = vic_result_file
        self.rout_input = rout_input_dir
        self.conda_hook = conda_hook
        self.model_path = os.path.join(vic_env, 'vic_image.exe')

    def run_vic(self, np=16, cd=None):
        log.log(NOTIFICATION, "Running VIC Model using %s cores", np)

        if cd:
            arg = f"source {self.conda_hook} && conda activate {self.vic_env} && cd {cd} && mpiexec -n  {np} {self.model_path} -g {self.param_file}"
        else:
            arg = f"source {self.conda_hook} && conda activate {self.vic_env} && mpiexec -n  {np} {self.model_path} -g {self.param_file}"

        ret_code = run_command(arg, shell=True)

    def disagg_results(self):
        log.log(NOTIFICATION, "Started disaggregating VIC results")
        fluxes = xr.open_dataset(self.vic_result).load()

        fluxes_subset = fluxes[['OUT_PREC', 'OUT_EVAP', 'OUT_RUNOFF', 'OUT_BASEFLOW', 'OUT_WDEW', 'OUT_SOIL_LIQ', 'OUT_SOIL_MOIST']]

        nonnans = fluxes_subset.OUT_PREC.isel(time=0).values.flatten()
        nonnans = nonnans[~np.isnan(nonnans)]
        total = len(nonnans)

        log.debug("Total files to be created: %s", total)

        create_directory(self.rout_input)

        # VIC Routing doesn't round, it truncates the lat long values. Important for file names.
        lats_vicfmt = np.array(list(map(lambda x: math.floor(x * 10 ** 2) / 10 ** 2, fluxes_subset.lat.values)))
        lons_vicfmt = np.array(list(map(lambda x: math.floor(x * 10 ** 2) / 10 ** 2, fluxes_subset.lon.values)))

        # with tqdm(total=total) as pbar:  # tqdm doesn't work elegantly with logging
        s = time.time()
        for lat in range(len(fluxes_subset.lat)):
            for lon in range(len(fluxes_subset.lon)):
                if not math.isnan(fluxes_subset.OUT_PREC.isel(time=0, lat=lat, lon=lon).values):
                    fname = os.path.join(self.rout_input, f"fluxes_{lats_vicfmt[lat]:.2f}_{lons_vicfmt[lon]:.2f}")
                    # pbar.set_description(f"{fname}")

                    da = fluxes_subset.isel(lat=lat, lon=lon, nlayer=0).to_dataframe().reset_index()

                    da.to_csv(fname, sep=' ', header=False, index=False, float_format="%.5f", quotechar="", quoting=csv.QUOTE_NONE, date_format="%Y %m %d", escapechar=" ")
                        # pbar.update(1)
        # See how many files were created
        disagg_n = len(os.listdir(self.rout_input))
        log.log(NOTIFICATION, "Finished disaggregating %s/%s files in %s seconds", disagg_n, total, f"{(time.time()-s):.3f}")
