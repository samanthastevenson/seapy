#!/usr/bin/env python
"""
  Functions to generate ROMS netcdf files

  Written by Brian Powell on 04/26/13
  Copyright (c)2013 University of Hawaii under the BSD-License.
"""
from __future__ import print_function

import os
import netCDF4
from datetime import datetime
from seapy.roms import lib
import seapy.cdl_parser as cdl_parser
import seapy.Null as Null

"""
    Module variables
"""
_cdl_dir = os.path.dirname(lib.__file__)
_cdl_dir =('.' if len(_cdl_dir) == 0 else _cdl_dir) + "/cdl/"

def ncgen(file, dims=Null(), vars=Null(), attr=Null(), title=None):
    """
        Create a new netcdf file
    """
    # Create the file
    _nc=netCDF4.Dataset(file, "w", format="NETCDF4_CLASSIC")
    # Loop over the dimensions and add them
    for dim in dims.keys():
        _nc.createDimension(dim, dims[dim])
    # Loop over the variables and add them
    for var in vars:
        if len(var["dims"][0]):
            nvar = _nc.createVariable( var["name"], var["type"], var["dims"])
        else:
            nvar = _nc.createVariable( var["name"], var["type"])
        if "attr" in var:
            for key in var["attr"]:
                setattr(nvar, key, var["attr"][key])
    # Add global attributes
    for a in attr:
        setattr(_nc, a, attr[a])
    _nc.author = os.getlogin()
    _nc.history = datetime.now().strftime("Created on %a, %B %d, %Y at %H:%M")
    if title != None:
        _nc.title = title
    _nc.close()
    return netCDF4.Dataset(file, "a")
    pass

def _set_grid_dimensions(dims, eta_rho, xi_rho, N):
    """
        Set grid dimensions
    """
    dims["xi_rho"] = xi_rho
    dims["xi_u"] = xi_rho-1
    dims["xi_v"] = xi_rho
    dims["xi_psi"] = xi_rho-1
    dims["eta_rho"] = eta_rho
    dims["eta_u"] = eta_rho
    dims["eta_v"] = eta_rho-1
    dims["eta_psi"] = eta_rho-1
    dims["N"] = N

    # Fill in the appropriate dimension values
    if dims.has_key("s_rho"):
        dims["s_rho"] = N
    if dims.has_key("s_w"):
        dims["s_w"] = N+1
    
    return dims

def _set_time_ref(vars, timevar, timebase, cycle=None):
    """
        Set time reference
    """
    if isinstance(timevar,str):
        timevar=[timevar]
    for tvar in timevar:
        for nvar in vars:
            if nvar["name"] == tvar:
                nvar["attr"]["units"] = timebase
                if cycle != None:
                    nvar["attr"]["cycle_length"] = cycle
    return vars
    
def _create_generic_file(file, cdl, eta_rho, xi_rho, N, 
                         timebase=None, title="ROMS"):
    """
        Generic file creator that uses ocean_time
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + cdl)

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    if timebase != None:
        vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_river(file, nriver=1, s_rho=5, 
                timebase=datetime(2000,1,1), title="My River"):
    """
        Create a new river file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "frc_rivers.cdl")
    
    # Fill in the appropriate river values
    dims["river"]=nriver
    vars = _set_time_ref(vars, "river_time", "days since %s" % timebase)

    # Create the river file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)
    
    # Return the new file
    return _nc

def create_grid(file, eta_rho=10, xi_rho=10, N=1, title="My Grid"):
    """
        Create a new grid file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "roms_grid.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    
    # Create the grid file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc
    
def create_adsen(file, eta_rho=10, xi_rho=10, N=1, 
                 timebase=datetime(2000,1,1), title="My Adsen"):
    """
        Create a new adjoint sensitivity file
    """
    # Create the general file
    return _create_generic_file(file, "adsen.cdl", eta_rho, xi_rho, N,
                                timebase, title)

def create_bry(file, eta_rho=10, xi_rho=10, N=1, 
                 timebase=datetime(2000,1,1), title="My BRY"):
    """
        Create a bry forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "bry_unlimit.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "bry_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc
    
def create_clim(file, eta_rho=10, xi_rho=10, N=1, ntimes=1, 
                 timebase=datetime(2000,1,1), title="My CLIM"):
    """
        Create a climatology forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "clm_ts.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    times=("zeta_time", "v2d_time", "v3d_time", "temp_time", "salt_time")
    for n in times:
        dims[n] = ntimes 
    vars = _set_time_ref(vars, times, "days since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc
    
def create_frc_bulk(file, eta_rho=10, xi_rho=10, N=1, 
                 timebase=datetime(2000,1,1), title="My Forcing"):
    """
        Create a bulk flux forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "frc_bulk.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_frc_flux(file, eta_rho=10, xi_rho=10, N=1, cycle=None, 
                 timebase=datetime(2000,1,1), title="My Flux"):
    """
        Create a surface flux forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "frc_fluxclm.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "srf_time", "seconds since %s" % timebase, cycle)
    vars = _set_time_ref(vars, "sst_time", "seconds since %s" % timebase, cycle)
    vars = _set_time_ref(vars, "shf_time", "seconds since %s" % timebase, cycle)
    vars = _set_time_ref(vars, "swf_time", "seconds since %s" % timebase, cycle)
    vars = _set_time_ref(vars, "sss_time", "seconds since %s" % timebase, cycle)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_frc_wind(file, eta_rho=10, xi_rho=10, N=1, cycle=None, 
                 timebase=datetime(2000,1,1), title="My Winds"):
    """
        Create a surface wind stress forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "frc_windstress.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "sms_time", "seconds since %s" % timebase, cycle)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_tide(file, eta_rho=10, xi_rho=10, N=1, ntides=1, 
                 timebase=datetime(2000,1,1), title="My Tides"):
    """
        Create a barotropic tide forcing file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "frc_tides.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    dims["tide_period"] = ntides

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_ini(file, eta_rho=10, xi_rho=10, N=1, 
                 timebase=datetime(2000,1,1), title="My Ini"):
    """
        Create an initial condition file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "ini_hydro.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_obs(file, state_variable=20, provenance="None",
                 timebase=datetime(2000,1,1), title="My Observations"):
    """
        Create an assimilation observations file
    """
                 
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_obs.cdl")

    # Fill in the appropriate dimension values
    dims["state_variable"] = state_variable
    vars = _set_time_ref(vars, "obs_time", "days since %s" % timebase)

    # Set the provenance values in the global attributes
    attr["obs_provenance"] = provenance
    
    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_ray_obs(file, ray_datum=1, provenance="None",
                 timebase=datetime(2000,1,1), title="My Observations"):
    """
        Create an assimilation observations file
    """
                 
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_obs_ray.cdl")

    # Fill in the appropriate dimension values
    dims["ray_datum"] = ray_datum
    vars = _set_time_ref(vars, "obs_time", "days since %s" % timebase)

    # Set the provenance values in the global attributes
    attr["obs_provenance"] = provenance
    
    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_bry_std(file, eta_rho=10, xi_rho=10, N=1, bry=4,
                  timebase=datetime(2000,1,1), title="My BRY STD"):
    """
        Create a boundaries standard deviation file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_std_b.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    dims["IorJ"] = max(eta_rho,xi_rho)
    dims["boundary"] = bry
    vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_frc_std(file, eta_rho=10, xi_rho=10, N=1,
                  timebase=datetime(2000,1,1), title="My FRC STD"):
    """
        Create a forcing standard deviation file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_std_f.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_ini_std(file, eta_rho=10, xi_rho=10, N=1,
                  timebase=datetime(2000,1,1), title="My INI STD"):
    """
        Create an initialization standard deviation file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_std_i.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_da_model_std(file, eta_rho=10, xi_rho=10, N=1,
                  timebase=datetime(2000,1,1), title="My Model STD"):
    """
        Create an time varying model standard deviation file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "s4dvar_std_m.cdl")

    # Fill in the appropriate dimension values
    dims = _set_grid_dimensions(dims, eta_rho, xi_rho, N)
    vars = _set_time_ref(vars, "ocean_time", "seconds since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

def create_zlevel(file, lat=10, lon=10, depth=1,
                  timebase=datetime(2000,1,1), 
                  title="Zlevel Model Data"):
    """
        Create an time varying model standard deviation file
    """
    # Generate the Structure
    dims, vars, attr = cdl_parser.cdl_parser(_cdl_dir + "zlevel.cdl")

    # Fill in the appropriate dimension values
    dims["lat"]=lat
    dims["lon"]=lon
    dims["depth"]=depth
    vars = _set_time_ref(vars, "time", "days since %s" % timebase)

    # Create the file
    _nc = ncgen(file, dims=dims, vars=vars, attr=attr, title=title)

    # Return the new file
    return _nc

if __name__ == "__main__":
    grid = create_zlevel("test.nc")
                                         
    