#!/usr/bin/env python
"""
  roms.interp
  
  Methods to interpolate ROMS fields onto other grids

  Written by Brian Powell on 11/02/13
  Copyright (c)2013 University of Hawaii under the BSD-License.
"""
from __future__ import print_function

import numpy as np
import netCDF4
import netcdftime
import os.path
import seapy
from joblib import Parallel, delayed
import pudb

def _mask_z_grid(z_data, src_depth, z_depth):
    """
    When interpolating to z-grid, we need to apply depth dependent masking
    based on the original ROMS depths
    """
    min_depth = np.min(src_depth,0)
    for k in np.arange(0,z_depth.shape[0]):
        idx=np.nonzero(z_depth[k,:,:]<min_depth)
        z_data.mask[:,k,idx[0],idx[1]]=True
        
def _interp2_thread(rx, ry, data, zx, zy, pmap, weight, nx, ny, mask):
    # Convolve the water over the land
    seapy.convolve_mask(data, 7)
    
    # Interpolate the field and return the result
    res, pm = seapy.oasurf(rx, ry, data, zx, zy, pmap, weight, nx, ny)
    return np.ma.array(res, mask=np.logical_or(mask==0,np.abs(res)>9e10), 
                       copy=False)

def _interp3_thread(rx, ry, rz, data, zx, zy, zz, pmap, 
                    weight, nx, ny, mask, factor=1.0):
    # Make the mask 3D
    mask = seapy.adddim(mask, zz.shape[0])
    
    # To avoid extrapolation, add a new top and bottom layer that replicates 
    # the data of the existing current and top. 1) Determine which way the 
    # depth goes and add/subtract new layers, and 2) fill in masked values
    # from the layer above/below.
    gradsrc = (rz[0,1,1]-rz[-1,1,1]) > 0
    graddest = (zz[0,1,1]-zz[-1,1,1]) > 0
    nrz = np.zeros((data.shape[0]+2,data.shape[1],data.shape[2]))
    nrz[1:-1,:,:]=rz
    if not gradsrc:
        # The first level is the bottom
        nrz[0,:,:]=rz[0,:,:]-500
        nrz[-1,:,:]=np.minimum(rz[-1,:,:]+50,0)
        # Fill in missing values where we have them from above (level above)
        for k in np.arange(data.shape[0]-2,-1,-1):
            idx=np.nonzero(np.logical_xor(data.mask[k,:,:],data.mask[k+1,:,:]))
            data.mask[k,idx[0],idx[1]]=data.mask[k+1,idx[0],idx[1]]
            data[k,idx[0],idx[1]]=data[k+1,idx[0],idx[1]]*factor
    else:
        # The first level is the top
        nrz[0,:,:]=np.minimum(rz[0,:,:]+50,0)
        nrz[-1,:,:]=rz[-1,:,:]-500
        # Fill in missing values where we have them from above (level below)
        for k in np.arange(1,data.shape[0]):
            idx=np.nonzero(np.logical_xor(data.mask[k,:,:],data.mask[k-1,:,:]))
            data.mask[k,idx[0],idx[1]]=data.mask[k-1,idx[0],idx[1]]
            data[k,idx[0],idx[1]]=data[k-1,idx[0],idx[1]]*factor

    # Convolve the water over the land
    seapy.convolve_mask(data, 7)

    # Add upper and lower boundaries
    ndat = np.zeros((data.shape[0]+2,data.shape[1],data.shape[2]))
    ndat[0,:,:]=data[0,:,:].filled(np.nan)*factor
    ndat[1:-1,:,:]=data.filled(np.nan)
    ndat[-1,:,:]=data[-1,:,:].filled(np.nan)*factor

    # Interpolate the field and return the result
    if gradsrc:
        res, pm = seapy.oavol(rx, ry, \
                    nrz[np.arange(nrz.shape[0]-1,-1,-1),:,:], \
                    ndat[np.arange(nrz.shape[0]-1,-1,-1),:,:], \
                    zx, zy, zz, pmap, \
                    weight, nx, ny)
    else:
        res, pm = seapy.oavol(rx, ry, nrz, ndat, zx, zy, zz, \
                            pmap, weight, nx, ny)
    return np.ma.array(res, mask=np.logical_or(mask==0,np.abs(res)>9e10), 
                       copy=False)

def _interp3_vel_thread(rx, ry, rz, ra, u, v, zx, zy, zz, za, pmap, 
                    weight, nx, ny, mask):
    # Put on the same grid
    if u.shape != v.shape:
        u = seapy.model.u2rho(u)
        v = seapy.model.v2rho(v)

    # Rotate the fields (NOTE: ROMS angle is negative relative to "true")
    if ra is not None:
        u, v = seapy.rotate(u, v, ra)

    # Interpolate
    u = _interp3_thread(rx, ry, rz, u, zx, zy, zz, pmap, 
                        weight, nx, ny, mask, 0.1)
    v = _interp3_thread(rx, ry, rz, v, zx, zy, zz, pmap, 
                        weight, nx, ny, mask, 0.1)
    
    # Rotate to destination (NOTE: ROMS angle is negative relative to "true")
    if za is not None:
        u, v = seapy.rotate(u, v, -za)

    # Return the masked data
    return u, v
        
def _interp_grids(src_grid, child_grid, ncout, records=None, 
            threads=1, nx=0, ny=0, vmap=None, z_mask=False):
    """
    _interp_grids(src_grid, ncout[, child_grid=None, records=None, 
                threads=1, nx=0, ny=0, vmap=None])
                
    Given a model file (average, history, etc.), interpolate the fields
    onto another gridded file. 
    
    Parameters
    ----------
    src_grid : seapy.model.grid data source (History, Average, etc. file)
    child_grid : seapy.model.grid output data grid
    ncout : netcdf output file
    [records] : array of the record indices to interpolate
    [threads] : number of processing threads
    [nx] : decorrelation length in grid-cells for x
    [ny] : decorrelation length in grid-cells for y
    [vmap] : variable name mapping
    [z_mask] : mask out depths in z-grids
    
    Returns
    -------
    None
    
    """
    # If we don't have a variable map, then do a one-to-one mapping
    if vmap is None:
        vmap=dict()
        for k in seapy.roms.fields.keys():
            vmap[k]=k

    # Generate a file to store the pmap information
    sname = src_grid.name
    cname = child_grid.name
    pmap_file = sname + "_" + cname + "_pmap.npz"

    # Create or load the pmaps depending on if they exist
    weight=8
    if nx==0 and hasattr(src_grid,"dm") and hasattr(child_grid,"dm"):
        nx = np.ceil( np.round( np.mean( (src_grid.dm / \
                    child_grid.dm).flatten() ),1))
    else:
        nx = 5
    if ny==0 and hasattr(src_grid,"dn") and hasattr(child_grid,"dn"):
        ny = np.ceil( np.round( np.mean( (src_grid.dn / \
                    child_grid.dn).flatten() ),1))
    else:
        ny = 5
        
    if os.path.isfile(pmap_file):
        pmap = np.load(pmap_file)
    else:
        tmp = np.ones(src_grid.lat_rho.shape,order="F")
        tmp, pmaprho = seapy.oasurf(src_grid.lon_rho, src_grid.lat_rho, \
                            tmp, child_grid.lon_rho, child_grid.lat_rho, \
                            weight=weight, nx=nx, ny=ny)
        tmp = np.ones(src_grid.lat_u.shape,order="F")
        tmp, pmapu = seapy.oasurf(src_grid.lon_u, src_grid.lat_u, \
                            tmp, child_grid.lon_rho, child_grid.lat_rho, \
                            weight=weight, nx=nx, ny=ny)
        tmp = np.ones(src_grid.lat_v.shape,order="F")
        tmp, pmapv = seapy.oasurf(src_grid.lon_v, src_grid.lat_v, \
                            tmp, child_grid.lon_rho, child_grid.lat_rho, \
                            weight=weight, nx=nx, ny=ny)
        np.savez(pmap_file, pmaprho=pmaprho, pmapu=pmapu, pmapv=pmapv)
        pmap = {"pmaprho":pmaprho, "pmapu":pmapu, "pmapv":pmapv}
        
    # Get the time field
    ncsrc = netCDF4.Dataset(src_grid.file)
    time = seapy.roms.get_timevar(ncsrc)
    
    # Interpolate the scalar fields
    records = np.arange(0, len(ncsrc.variables[time][:])) \
                 if records == None else records
    for k in vmap:
        # Only interpolate the fields we want in the destination
        if vmap[k] not in ncout.variables or \
           seapy.roms.fields[vmap[k]].has_key("rotate"):
            continue
        grd = seapy.roms.fields[vmap[k]]["grid"]
        if seapy.roms.fields[vmap[k]]["dims"]==2:
            ndata = np.ma.array(Parallel(n_jobs=threads,verbose=2)\
                             (delayed(_interp2_thread) (
              getattr(src_grid,"lon_"+grd), getattr(src_grid,"lat_"+grd),
              ncsrc.variables[k][i,:,:],
              getattr(child_grid,"lon_"+grd), getattr(child_grid,"lat_"+grd),
              pmap["pmap"+grd], weight,
              nx, ny, getattr(child_grid,"mask_"+grd)) 
            for i in records), copy=False)
        else:
            ndata = np.ma.array( Parallel(n_jobs=threads,verbose=2)
                             (delayed(_interp3_thread)( 
              getattr(src_grid,"lon_"+grd), getattr(src_grid,"lat_"+grd),
              getattr(src_grid,"depth_"+grd),
              ncsrc.variables[k][i,:,:,:],
              getattr(child_grid,"lon_"+grd), getattr(child_grid,"lat_"+grd),
              getattr(child_grid,"depth_"+grd),
              pmap["pmap"+grd], weight,
              nx, ny, getattr(child_grid,"mask_"+grd)) 
            for i in records), copy=False)
            if z_mask:
                _mask_z_grid(ndata,getattr(src_grid,"depth_"+grd),
                             getattr(child_grid,"depth_"+grd))
        ncout.variables[vmap[k]][:] = ndata

    # Rotate and Interpolate the vector fields
    if ( vmap.has_key("u") and vmap["u"] in ncout.variables ) and \
       ( vmap.has_key("v") and vmap["v"] in ncout.variables ):
        srcangle = src_grid.angle if src_grid.cgrid is True else None
        dstangle = child_grid.angle if child_grid.cgrid is True else None
        vel = Parallel(n_jobs=threads, verbose=2) \
                 (delayed(_interp3_vel_thread)( \
            src_grid.lon_rho, src_grid.lat_rho, \
            src_grid.depth_rho, srcangle, \
            ncsrc.variables["u"][i,:,:,:], \
            ncsrc.variables["v"][i,:,:,:], \
            child_grid.lon_rho, child_grid.lat_rho, \
            child_grid.depth_rho, dstangle, \
            pmap["pmaprho"], weight, nx, ny,  \
            child_grid.mask_rho) for i in records)

        for j in np.arange(0,len(vel)):
            vel_u = np.ma.array(vel[j][0],copy=False)
            vel_v = np.ma.array(vel[j][1],copy=False)
            if z_mask:
                _mask_z_grid(vel_u,src_grid.depth_rho,child_grid.depth_rho)
                _mask_z_grid(vel_v,src_grid.depth_rho,child_grid.depth_rho)

            if child_grid.cgrid is True:
                vel_u = seapy.model.rho2u(vel_u)
                vel_v = seapy.model.rho2v(vel_v)


            ncout.variables[vmap["u"]][j,:] = vel_u
            ncout.variables[vmap["v"]][j,:] = vel_v

            if vmap.has_key("ubar") and vmap["ubar"] in ncout.variables:
                # Create ubar and vbar
                depth = seapy.adddim(child_grid.depth_u, vel_u.shape[0])
                ncout.variables[vmap["ubar"]][j,:] = \
                    np.sum(vel_u * depth, 1) / np.sum(depth, 1)

            if vmap.has_key("vbar") and vmap["vbar"] in ncout.variables:
                depth = seapy.adddim(child_grid.depth_v, vel_v.shape[0])
                ncout.variables[vmap["vbar"]][j,:] = \
                    np.sum(vel_v * depth, 1) / np.sum(depth, 1)

# def to_grid(src_file, dest_file, dest_grid=None, records=None, threads=1,
#             nx=0, ny=0, vmap=None):
#     # Figure out the file structures
#     if os.path.isfile(src_file):
#         if dest_grid != None:
#             if isinstance(dest_grid,basestring):
#                 dest_grid = seapy.model.grid(dest_grid)
#         else:
#             dest_grid=seapy.model.grid(dest_file)
#         src_grid = seapy.model.grid(src_file)
#         ncout=netCDF4.Dataset(dest_file,"a")
#     
#     # Call the base interpolator
#     _interp_grids(src_grid, dest_grid, ncout, records, threads, nx, ny, vmap)
#         
#     # Clean up
#     ncout.close()

def to_zgrid(roms_file, z_file, z_grid=None, depth=None, records=None, 
             threads=1, nx=0, ny=0, vmap=None):
    """
    to_zgrid(roms_file, z_file, z_grid=None, depth=None, records=None, 
                 threads=1, nx=0, ny=0)
                 
    Given an existing ROMS history or average file, create (if does not exit)
    a new z-grid file. Use the given z_grid or otherwise build one with the 
    same horizontal extent and the specified depths and interpolate the 
    ROMS fields onto the z-grid.
    
    Parameters
    ----------
    roms_file : Name of ROMS file to interpolate from
    z_file : Name of Z-grid file to write to
    [z_grid] : (string or seapy.model.grid) Name or instance of z-grid definition
    [depth] : array of depths to use for z-level
    [records] : array of the record indices to interpolate
    [threads] : number of processing threads
    [nx] : decorrelation length in grid-cells for x
    [ny] : decorrelation length in grid-cells for y
    [vmap] : dictionary mapping source and destination variables
    
    Returns
    -------
    None
    
    """
    roms_grid = seapy.model.grid(roms_file, minimal=False)
    ncroms = netCDF4.Dataset(roms_file)
    time = seapy.roms.get_timevar(ncroms)
    src_time = netcdftime.utime(ncroms.variables[time].units)
    records = np.arange(0, len(ncroms.variables[time][:])) \
             if records == None else records

    if z_grid != None:
        if isinstance(z_grid,basestring):
            z_grid = seapy.model.grid(z_grid, minimal=False)
    else:
        if os.path.isfile(z_file):
            z_grid = seapy.model.grid(z_file, minimal=False)
            ncout = netCDF4.Dataset(z_file, "a")
            
    if not os.path.isfile(z_file):
        if z_grid is None:
            lat=roms_grid.lat_rho.shape[0]
            lon=roms_grid.lat_rho.shape[1]
            if depth==None:
                raise ValueError("depth must be specified")
            ncout=seapy.roms.ncgen.create_zlevel(z_file,lat,lon,len(depth),
                                   src_time.origin,"ROMS z-level")
            ncout.variables["lat"][:]=roms_grid.lat_rho
            ncout.variables["lon"][:]=roms_grid.lon_rho
            ncout.variables["depth"][:]=depth
            ncout.variables["mask"][:]=roms_grid.mask_rho
            ncout.sync()
            z_grid = seapy.model.grid(z_file, minimal=False)
        else:
            lat=z_grid.lat_rho.shape[0]
            lon=z_grid.lat_rho.shape[1]
            ncout=seapy.roms.ncgen.create_zlevel(z_file,lat,lon,len(z_grid.depth),
                               src_time.origin,"ROMS z-level")
            ncout.variables["lat"][:]=z_grid.lat_rho
            ncout.variables["lon"][:]=z_grid.lon_rho
            ncout.variables["depth"][:]=z_grid.depth
            ncout.variables["mask"][:]=z_grid.mask_rho
    ncout_time = netcdftime.utime(ncout.variables["time"].units)
    ncout.variables["time"][:]=\
      ncout_time.date2num(src_time.num2date(ncroms.variables[time][records]))
    ncroms.close()
    
    # Call the interpolation
    _interp_grids(roms_grid, z_grid, ncout, records=records,
                  threads=threads, nx=nx, ny=ny, vmap=vmap, z_mask=True)

    # Clean up
    ncout.close()
    
def to_grid(src_file, dest_file, dest_grid=None, records=None, threads=1,
            vmap=None):
    """
    to_grid(src_file, dest_file, dest_grid=None, records=None, threads=1)
    
    Given an existing model file, create (if does not exit) a
    new ROMS history file using the given ROMS destination grid and
    interpolate the ROMS fields onto the new grid. If an existing destination
    file is given, it is interpolated onto the specified.

    Parameters
    ----------
    src_file  : (string or seapy.model.grid) Name or instance of src file 
                to interpolate from
    dest_file : Name of desination file to write to
    [dest_grid]: (string or seapy.model.grid) Name or instance of output definition
    [records] : array of the record indices to interpolate
    [threads] : number of processing threads
    [vmap] : dictionary mapping source and destination variables
    
    Returns
    -------
    None
    """
    src_grid = seapy.model.grid(src_file, minimal=False)
    if dest_grid != None:
        if isinstance(dest_grid,basestring):
            destg = seapy.model.grid(dest_grid, minimal=False)
        else:
            destg = dest_grid
        
        if not os.path.isfile(dest_file):
            ncsrc = netCDF4.Dataset(src_file)
            time = seapy.roms.get_timevar(ncsrc)
            records = np.arange(0, len(ncsrc.variables[time][:])) \
                     if records == None else records
            src_time=netcdftime.utime(ncsrc.variables[time].units)
            ncout=seapy.roms.ncgen.create_ini(dest_file, 
                     eta_rho=destg.ln,xi_rho=destg.lm,N=destg.n,
                     timebase=src_time.origin,title="interpolated from "+src_file)
            ncout.variables["lat_rho"][:]=destg.lat_rho
            ncout.variables["lon_rho"][:]=destg.lon_rho
            ncout.variables["lat_u"][:]=destg.lat_u
            ncout.variables["lon_u"][:]=destg.lon_u
            ncout.variables["lat_v"][:]=destg.lat_v
            ncout.variables["lon_v"][:]=destg.lon_v
            ncout.variables["Vtransform"][:]=destg.vtransform
            ncout.variables["Vstretching"][:]=destg.vstretching
            ncout.variables["theta_s"][:]=destg.theta_s
            ncout.variables["theta_b"][:]=destg.theta_b
            ncout.variables["hc"][:]=destg.hc
            ncout.variables["Tcline"][:]=destg.tcline
            ncout.variables["s_rho"][:]=destg.s_rho
            ncout.variables["Cs_r"][:]=destg.cs_r
            ncout.variables["h"][:]=destg.h
            dest_time = netcdftime.utime(ncout.variables["ocean_time"].units)
            ncout.variables["ocean_time"][:]=dest_time.date2num(
                src_time.num2date(ncsrc.variables[time][records]))
            ncsrc.close()

    if os.path.isfile(dest_file):
        ncout = netCDF4.Dataset(dest_file,"a")
        if dest_grid == None:
            destg = seapy.model.grid(dest_file, minimal=False)

    # Call the interpolation
    _interp_grids(src_grid, destg, ncout, records=records, threads=threads,
                  vmap=vmap)

    # Clean up
    ncout.close()

def to_clim(src_file, dest_file, dest_grid=None, records=None, threads=1,
            vmap=None):
    """
    to_clim(src_file, dest_file, dest_grid=None, records=None, threads=1)
    
    Given an model output file, create (if does not exit) a
    new ROMS climatology file using the given ROMS destination grid and
    interpolate the ROMS fields onto the new grid. If an existing destination
    file is given, it is interpolated onto the specified.

    Parameters
    ----------
    src_file  : (string or seapy.model.grid) Name or instance of src file 
                to interpolate from
    dest_file : Name of desination file to write to
    [dest_grid]: (string or seapy.model.grid) Name or instance of output definition
    [records] : array of the record indices to interpolate
    [threads] : number of processing threads
    [vmap] : dictionary mapping source and destination variables
    
    Returns
    -------
    None
    """
    if dest_grid != None:
        if isinstance(dest_grid,basestring):
            destg = seapy.model.grid(dest_grid, minimal=False)
        else:
            destg = dest_grid
            
        src_grid = seapy.model.grid(src_file, minimal=False)
        ncsrc = netCDF4.Dataset(src_file)
        time = seapy.roms.get_timevar(ncsrc)
        records = np.arange(0, len(ncsrc.variables[time][:])) \
                 if records == None else records
        src_time=netcdftime.utime(ncsrc.variables[time].units)
        ncout=seapy.roms.ncgen.create_clim(dest_file, 
                 eta_rho=destg.ln,xi_rho=destg.lm,N=destg.n,ntimes=records.size,
                 timebase=src_time.origin,title="interpolated from "+src_file)
        dest_time = netcdftime.utime(ncout.variables["zeta_time"].units)
        ncout.variables["zeta_time"][:] = dest_time.date2num(
                 src_time.num2date(ncsrc.variables[time][records]))
        ncout.variables["v2d_time"][:] = dest_time.date2num(
                 src_time.num2date(ncsrc.variables[time][records]))
        ncout.variables["v3d_time"][:] = dest_time.date2num(
                 src_time.num2date(ncsrc.variables[time][records]))
        ncout.variables["temp_time"][:] = dest_time.date2num(
                 src_time.num2date(ncsrc.variables[time][records]))
        ncout.variables["salt_time"][:] = dest_time.date2num(
                 src_time.num2date(ncsrc.variables[time][records]))
        ncsrc.close()
    else:
        raise AttributeError("you must supply a destination file or a grid to make the file")

    # Call the interpolation
    _interp_grids(src_grid, destg, ncout, records=records, threads=threads,
                  vmap=vmap)

    # Clean up
    ncout.close()
    
pass