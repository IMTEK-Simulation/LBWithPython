"""
Copyright 2017-2018 Lars Pastewka, Andreas Greiner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

--------
| OPT1 |
--------

This is an implementation of the D2Q9 Lattice Boltzmann lattice in the simple
relaxation time approximation. The writes the velocity field to a series of
files in the npy format.

The present implementation contains was optimized with respect to opt0 to
eliminate all multiplications with zero (channel velocity) in the collision
step. This requires to explicitly write out some multiplication from opt0. The
storage of the velocity field is split into the two Cartesian components ux_kl
and uy_kl now rather than having a single array u_ckl with Cartesian index as
the first dimension.
"""

import sys

from enum import IntEnum

from mpi4py import MPI

import numpy as np

from PyLB.IO import save_mpiio

### Parameters

# Decomposition
ndx = int(sys.argv[1])
ndy = int(sys.argv[2])

# Lattice
nx = int(sys.argv[3])
ny = int(sys.argv[4])

# Data type
dtype = np.dtype(sys.argv[5])

# Number of steps
nsteps = 100000

# Dump velocities every this many steps
dump_freq = 10000

# Relaxation parameter
omega = np.array(1.7, dtype=dtype)

### Direction shorthands

D = IntEnum('D', 'E N W S NE NW SW SE')

### Auxiliary arrays

# Naming conventions for arrays: Subscript indicates type of dimension
# Example: c_ic <- 2-dimensional array
#            ^^
#            ||--- c: Cartesion index, can have value 0 or 1
#            |---- i: Channel index, can have value 0 to 8
# Example: f_ikl <- 3-dimensional array
#            ^^^
#            |||--- l: y-position, can have value 0 to ny-1
#            ||---- k: x-position, can have value 0 to nx-1
#            |----- i: Channel index, can value 0 to 8

# "Velocities" of individual channels
c_ic = np.array([[0,  1,  0, -1,  0,  1, -1, -1,  1],    # velocities, x components
                 [0,  0,  1,  0, -1,  1,  1, -1, -1]]).T # velocities, y components

# Weight factors
w_0 = 4/9
w_1234 = 1/9
w_5678 = 1/36
w_i = np.array([w_0, w_1234, w_1234, w_1234, w_1234,
                w_5678, w_5678, w_5678, w_5678], dtype=dtype)

### Compute functions

def equilibrium(rho_kl, ux_kl, uy_kl):
    """
    Return the equilibrium distribution function.

    Parameters
    ----------
    rho_rl: array
        Fluid density on the 2D grid.
    ux_kl: array
        x-components of streaming velocity on the 2D grid.
    uy_kl: array
        y-components of streaming velocity on the 2D grid.

    Returns
    -------
    f_ikl: array
        Equilibrium distribution for the given fluid density *rho_kl* and
        streaming velocity *ux_kl*, *uy_kl*.
    """
    cu5_kl = ux_kl + uy_kl
    cu6_kl = -ux_kl + uy_kl
    cu7_kl = -ux_kl - uy_kl
    cu8_kl = ux_kl - uy_kl
    uu_kl = ux_kl**2 + uy_kl**2
    return np.array([w_0*rho_kl*(1 - 3/2*uu_kl),
                     w_1234*rho_kl*(1 + 3*ux_kl + 9/2*ux_kl**2 - 3/2*uu_kl),
                     w_1234*rho_kl*(1 + 3*uy_kl + 9/2*uy_kl**2 - 3/2*uu_kl),
                     w_1234*rho_kl*(1 - 3*ux_kl + 9/2*ux_kl**2 - 3/2*uu_kl),
                     w_1234*rho_kl*(1 - 3*uy_kl + 9/2*uy_kl**2 - 3/2*uu_kl),
                     w_5678*rho_kl*(1 + 3*cu5_kl + 9/2*cu5_kl**2 - 3/2*uu_kl),
                     w_5678*rho_kl*(1 + 3*cu6_kl + 9/2*cu6_kl**2 - 3/2*uu_kl),
                     w_5678*rho_kl*(1 + 3*cu7_kl + 9/2*cu7_kl**2 - 3/2*uu_kl),
                     w_5678*rho_kl*(1 + 3*cu8_kl + 9/2*cu8_kl**2 - 3/2*uu_kl)])

def collide(f_ikl, omega):
    """
    Carry out collision step. This relaxes the distribution of particle
    velocities towards its equilibrium.

    Parameters
    ----------
    f_ikl: array
        Distribution of particle velocity on the 2D grid. Note that this array
        is modified in place.
    omega: float
        Relaxation parameter.

    Returns
    -------
    rho_rl: array
        Current fluid density on the 2D grid.
    ux_kl: array
        x-components of current streaming velocity on the 2D grid.
    uy_kl: array
        y-components of current streaming velocity on the 2D grid.
    """
    rho_kl = np.sum(f_ikl, axis=0)
    ux_kl = (f_ikl[1] - f_ikl[3] + f_ikl[5] - f_ikl[6] - f_ikl[7] + f_ikl[8])/rho_kl
    uy_kl = (f_ikl[2] - f_ikl[4] + f_ikl[5] + f_ikl[6] - f_ikl[7] - f_ikl[8])/rho_kl
    f_ikl += omega*(equilibrium(rho_kl, ux_kl, uy_kl) - f_ikl)
    return rho_kl, ux_kl, uy_kl

def stream(f_ikl):
    """
    Propagate channel occupations by one cell distance.

    Parameters
    ----------
    f_ikl : array
        Array containing the occupation numbers. Array is 3-dimensional, with
        the first dimension running from 0 to 8 and indicating channel. The
        next two dimensions are x- and y-position. This array is modified in
        place.
    """
    for i in range(1, 9):
        f_ikl[i] = np.roll(f_ikl[i], c_ic[i], axis=(0, 1))

def stream_and_bounce_back(f_ikl, u0=0.1):
    """
    Propagate channel occupations by one cell distance and apply no-slip 
    boundary condition to all four walls. The top wall can additionally have
    a velocity.

    Parameters
    ----------
    f_ikl : array
        Array containing the occupation numbers. Array is 3-dimensional, with
        the first dimension running from 0 to 8 and indicating channel. The
        next two dimensions are x- and y-position. This array is modified in
        place.
    u0 : float
        Velocity of the top wall.
    """
    fbottom_ik = f_ikl[:, :, 0].copy()
    ftop_ik = f_ikl[:, :, -1].copy()

    fleft_il = f_ikl[:, 0, :].copy()
    fright_il = f_ikl[:, -1, :].copy()

    stream(f_ikl)

    # Bottom boundary
    f_ikl[D.N, :, 0] = fbottom_ik[D.S]
    f_ikl[D.NE, :, 0] = fbottom_ik[D.SW]
    f_ikl[D.NW, :, 0] = fbottom_ik[D.SE]

    # Top boundary - sliding lid
    # We need to compute the rho *after* bounce back
    rhobottom_k = ftop_ik[D.NW] + ftop_ik[D.N] + ftop_ik[D.NE] + \
        f_ikl[D.NW, :, -1] + f_ikl[D.N, :, -1] + f_ikl[D.NE, :, -1] + \
        f_ikl[D.W, :, -1] + f_ikl[0, :, -1] + f_ikl[D.E, :, -1]
    f_ikl[D.S, :, -1] = ftop_ik[D.N]
    f_ikl[D.SE, :, -1] = ftop_ik[D.NW] + 6*w_i[D.SE]*rhobottom_k*u0
    f_ikl[D.SW, :, -1] = ftop_ik[D.NE] - 6*w_i[D.SW]*rhobottom_k*u0

    # Change to "if False" for Couette flow test
    if True:
        # Left boundary
        f_ikl[D.E, 0, :] = fleft_il[D.W]
        f_ikl[D.NE, 0, :] = fleft_il[D.SW]
        f_ikl[D.SE, 0, :] = fleft_il[D.NW]

        # Right boundary
        f_ikl[D.W, -1, :] = fright_il[D.E]
        f_ikl[D.NW, -1, :] = fright_il[D.SE]
        f_ikl[D.SW, -1, :] = fright_il[D.NE]

        # Bottom-left corner
        f_ikl[D.N, 0, 0] = fbottom_ik[D.S, 0]
        f_ikl[D.E, 0, 0] = fbottom_ik[D.W, 0]
        f_ikl[D.NE, 0, 0] = fbottom_ik[D.SW, 0]

        # Bottom-right corner
        f_ikl[D.N, -1, 0] = fbottom_ik[D.S, -1]
        f_ikl[D.W, -1, 0] = fbottom_ik[D.E, -1]
        f_ikl[D.NW, -1, 0] = fbottom_ik[D.SE, -1]

        # Top-left corner
        f_ikl[D.S, 0, -1] = ftop_ik[D.N, 0]
        f_ikl[D.E, 0, -1] = ftop_ik[D.W, 0]
        f_ikl[D.SE, 0, -1] = ftop_ik[D.NW, 0]

        # Top-right corner
        f_ikl[D.S, -1, -1] = ftop_ik[D.N, -1]
        f_ikl[D.W, -1, -1] = ftop_ik[D.E, -1]
        f_ikl[D.SW, -1, -1] = ftop_ik[D.NE, -1]

def communicate(f_ikl):
    """
    Communicate boundary regions to ghost regions.

    Parameters
    ----------
    f_ikl : array
        Array containing the occupation numbers. Array is 3-dimensional, with
        the first dimension running from 0 to 8 and indicating channel. The
        next two dimensions are x- and y-position. This array is modified in
        place.
    """
    # Send to left
    recvbuf = f_ikl[:, -1, :].copy()
    comm.Sendrecv(f_ikl[:, 1, :].copy(), left_dst,
                  recvbuf=recvbuf, source=left_src)
    f_ikl[:, -1, :] = recvbuf
    # Send to right
    recvbuf = f_ikl[:, 0, :].copy()
    comm.Sendrecv(f_ikl[:, -2, :].copy(), right_dst,
                  recvbuf=recvbuf, source=right_src)
    f_ikl[:, 0, :] = recvbuf
    # Send to bottom
    recvbuf = f_ikl[:, :, -1].copy()
    comm.Sendrecv(f_ikl[:, :, 1].copy(), bottom_dst,
                  recvbuf=recvbuf, source=bottom_src)
    f_ikl[:, :, -1] = recvbuf
    # Send to top
    recvbuf = f_ikl[:, :, 0].copy()
    comm.Sendrecv(f_ikl[:, :, -2].copy(), top_dst,
                  recvbuf=recvbuf, source=top_src)
    f_ikl[:, :, 0] = recvbuf

### Initialize MPI communicator

size = MPI.COMM_WORLD.Get_size()
rank = MPI.COMM_WORLD.Get_rank()
if rank == 0:
    print('Running in parallel on {} MPI processes.'.format(size))
assert ndx*ndy == size
if rank == 0:
    print('Domain decomposition: {} x {} MPI processes.'.format(ndx, ndy))
    print('Global grid has size {}x{}.'.format(nx, ny))
    print('Using {} floating point data type.'.format(dtype))

# Create cartesian communicator and get MPI ranks of neighboring cells
comm = MPI.COMM_WORLD.Create_cart((ndx, ndy), periods=(False, False))
left_src, left_dst = comm.Shift(0, -1)
right_src, right_dst = comm.Shift(0, 1)
bottom_src, bottom_dst = comm.Shift(1, -1)
top_src, top_dst = comm.Shift(1, 1)

local_nx = nx//ndx
local_ny = ny//ndy

# We need to take care that the total number of *local* grid points sums up to
# nx. The right and topmost MPI processes are adjusted such that this is
# fulfilled even if nx, ny is not divisible by the number of MPI processes.
if right_dst < 0:
    # This is the rightmost MPI process
    local_nx = nx - local_nx*(ndx-1)
without_ghosts_x = slice(0, local_nx)
if right_dst >= 0:
    # Add ghost cell
    local_nx += 1
if left_dst >= 0:
    # Add ghost cell
    local_nx += 1
    without_ghosts_x = slice(1, local_nx+1)
if top_dst < 0:
    # This is the topmost MPI process
    local_ny = ny - local_ny*(ndy-1)
without_ghosts_y = slice(0, local_ny)
if top_dst >= 0:
    # Add ghost cell
    local_ny += 1
if bottom_dst >= 0:
    # Add ghost cell
    local_ny += 1
    without_ghosts_y = slice(1, local_ny+1)

mpix, mpiy = comm.Get_coords(rank)
print('Rank {} has domain coordinates {}x{} and a local grid of size {}x{} (including ghost cells).'.format(rank, mpix, mpiy, local_nx, local_ny))

### Initialize occupation numbers

f_ikl = equilibrium(np.ones((local_nx, local_ny), dtype=dtype),
                    np.zeros((local_nx, local_ny), dtype=dtype),
                    np.zeros((local_nx, local_ny), dtype=dtype))
### Main loop

for i in range(nsteps):
    if i % 10 == 9:
        sys.stdout.write('=== Step {}/{} ===\r'.format(i+1, nsteps))
    communicate(f_ikl)
    stream_and_bounce_back(f_ikl)
    rho_kl, ux_kl, uy_kl = collide(f_ikl, omega)

    if i % dump_freq == 0:
        save_mpiio(comm, 'ux_{}.npy'.format(i), ux_kl[without_ghosts_x, without_ghosts_y])
        save_mpiio(comm, 'uy_{}.npy'.format(i), uy_kl[without_ghosts_x, without_ghosts_y])

### Dump final stage of the simulation to a file

save_mpiio(comm, 'ux_{}.npy'.format(i), u_ckl[0, without_ghosts_x, without_ghosts_y])
save_mpiio(comm, 'uy_{}.npy'.format(i), u_ckl[1, without_ghosts_x, without_ghosts_y])
