#!/usr/bin/env python
# coding: UTF-8
"""
Chebfun module
==============

.. moduleauthor :: Chris Swierczewski <cswiercz@gmail.com>
.. moduleauthor :: Olivier Verdier <olivier.verdier@gmail.com>
.. moduleauthor :: Gregory Potter <ghpotter@gmail.com>

"""
from __future__ import division

import operator

import numpy as np
from scipy import linalg  
import matplotlib.pyplot as plt

import sys
from functools import wraps

from scipy.interpolate import BarycentricInterpolator as Bary
import numpy.polynomial as poly

import scipy.fftpack as fftpack

def cast_scalar(method):
    """
    Used to cast scalar to Funs
    """
    @wraps(method)
    def new_method(self, other):
        if np.isscalar(other):
            other = type(self)([other],self.domain())
        return method(self, other)
    return new_method

emach     = sys.float_info.epsilon                        # machine epsilon



class Fun(object):
    """
    Construct a Lagrange interpolating polynomial over arbitrary points.
    Fun objects consist in essence of two components:
    
        1) An interpolant on [-1,1],
        2) A domain attribute [a,b].
        
    These two pieces of information are used to define and subsequently 
    keep track of operations upon Chebyshev interpolants defined on an 
    arbitrary real interval [a,b].

    """
    
    # ----------------------------------------------------------------
    # Initialisation methods
    # ----------------------------------------------------------------

    class NoConvergence(Exception):
        """
        Raised when dichotomy does not converge.
        """
        
    class DomainMismatch(Exception):
        """
        Raised when there is an interval mismatch between 
        """ 
        
    @classmethod
    def from_data(self, data, domain=[-1., 1.]):
        """
        Initialise from interpolation values.
        """
        return self(data,domain)

    @classmethod
    def from_fun(self, other):
        """
        Initialise from another instance of Fun
        """
        return self(other.values(),other.domain())

    @classmethod
    def from_chebcoeff(self, chebcoeff, domain=[-1., 1.], prune=True, vscale=1.):
        """
        Initialise from provided Chebyshev coefficients
        prune: Whether to prune the negligible coefficients
        vscale: the scale to use when pruning
        """
        coeffs = np.asarray(chebcoeff)
        if prune:
            N = self._cutoff(coeffs, vscale)
            pruned_coeffs = coeffs[:N]
        else:
            pruned_coeffs = coeffs
        values = self.chebpolyval(pruned_coeffs)
        return self(values, domain, vscale)

    @classmethod
    def dichotomy(self, f, kmin=2, kmax=12, raise_no_convergence=True,):
        """
        Compute the coefficients for a function f by dichotomy.
        kmin, kmax: log2 of number of interpolation points to try
        raise_no_convergence: whether to raise an exception if the dichotomy does not converge
        """

        for k in xrange(kmin, kmax):
            N = pow(2, k)

            sampled = self.sample_function(f, N)
            coeffs = self.chebpolyfit(sampled)

            # 3) Check for negligible coefficients
            #    If within bound: get negligible coeffs and bread
            bnd = self._threshold(np.max(np.abs(coeffs)))

            last = abs(coeffs[-2:])
            if np.all(last <= bnd):
                break
        else:
            if raise_no_convergence:
                raise self.NoConvergence(last, bnd)
        return coeffs

    @classmethod
    def from_function(self, f, domain=[-1., 1.], N=None):
        """
        Initialise from a function to sample.
        N: optional parameter which indicates the range of the dichotomy
        """
        # rescale f to the unit domain 
        a,b = domain[0], domain[-1]
        map_ui_ab = lambda t: 0.5*(b-a)*t + 0.5*(a+b) 
        args = {'f': lambda t: f(map_ui_ab(t))}
        if N is not None: # N is provided
            nextpow2 = int(np.log2(N))+1
            args['kmin'] = nextpow2
            args['kmax'] = nextpow2+1
            args['raise_no_convergence'] = False
        else:
            args['raise_no_convergence'] = True

        # Find out the right number of coefficients to keep
        coeffs = self.dichotomy(**args)

        return self.from_chebcoeff(coeffs, domain)

    @classmethod
    def _threshold(self, vscale):
        """
        Compute the threshold at which Chebyshev coefficients are trimmed.
        """
        bnd = 128*emach*vscale
        return bnd

    @classmethod
    def _cutoff(self, coeffs, vscale):
        """
        Compute cutoff index after which the coefficients are deemed negligible.
        """
        bnd = self._threshold(vscale)
        inds  = np.nonzero(abs(coeffs) >= bnd)
        if len(inds[0]):
            N = inds[0][-1]
        else:
            N = 0
        return N+1
 
 
    def __init__(self, values=0., domain=[-1., 1.], vscale=None):
        """
        Init a Fun object from values at Chebyshev points.
        values: Interpolation values
        vscale: The actual vscale; computed automatically if not given
        """
        avalues = np.asarray(values,)
        avalues1 = np.atleast_1d(avalues)
        N = len(avalues1)
        points = self.interpolation_points(N)
        self._values = avalues1
        if vscale is not None:
            self._vscale = vscale
        else:
            self._vscale = np.max(np.abs(self._values))
        self.p = self.interpolator(points, avalues1)

        self._domain = np.array(domain)
        a,b = domain[0], domain[-1]
        
        # maps from [-1,1] <-> [a,b]
        self._ab_to_ui = lambda x: (2.0*x-a-b)/(b-a)
        self._ui_to_ab = lambda t: 0.5*(b-a)*t + 0.5*(a+b) 
 

    # ----------------------------------------------------------------
    # String representations
    # ----------------------------------------------------------------

    def __repr__(self):
        """
        Display method
        """
        a, b = self.domain()
        vals = self.values()
        return (
            '%s \n ' 
            '    domain        length     endpoint values\n '
            ' [%5.1f, %5.1f]     %5d       %5.2f   %5.2f\n '
            'vscale = %1.2e') % (
                str(type(self)).split('.')[-1].split('>')[0][:-1],
                a,b,self.size(),vals[-1],vals[0],self._vscale,)    

    def __str__(self):
        return "<{0}({1})>".format(
            str(type(self)).split('.')[-1].split('>')[0][:-1],self.size(),)

    # ----------------------------------------------------------------
    # Basic Operator Overloads
    # ----------------------------------------------------------------

    def __call__(self, x):
        return self.p(self._ab_to_ui(x))

    def __getitem__(self, s):
        """
        Components s of the fun.
        """
        return self.from_data(self.values().T[s].T)

    def __nonzero__(self):
        """
        Test for difference from zero (up to tolerance)
        """
        return not np.allclose(self.values(), 0)

    def __eq__(self, other):
        return not(self - other)

    def __neq__(self, other):
        return not (self == other)

    @cast_scalar
    def __add__(self, other):
        """
        Addition
        """
        if not same_domain(self,other):
            raise self.DomainMismatch(self.domain(),other.domain())
            
        ps = [self, other]
        # length difference
        diff = other.size() - self.size()
        # determine which of self/other is the smaller/bigger
        big = diff > 0
        small = not big
        # pad the chebyshev coefficients of the small one with zeros
        small_coeffs = ps[small].chebyshev_coefficients()
        big_coeffs = ps[big].chebyshev_coefficients()
        padded = np.zeros_like(big_coeffs)
        padded[:len(small_coeffs)] = small_coeffs
        # add the values and create a new Fun with them
        chebsum = big_coeffs + padded
        new_vscale = np.max([self._vscale, other._vscale])
        return self.from_chebcoeff(
            chebsum, domain=self.domain(), vscale=new_vscale
        )

    __radd__ = __add__


    @cast_scalar
    def __sub__(self, other):
        """
        Fun subtraction.
        """
        return self + (-other)

    def __rsub__(self, other):
        return -(self - other)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        return self.__div__(other)

    def __rtruediv__(self, other):
        return self.__rdiv__(other)

    def __neg__(self):
        """
        Fun negation.
        """
        return self.from_data(-self.values(),domain=self.domain())


    def __abs__(self):
        return self.from_function(lambda x: abs(self(x)),domain=self.domain())

    # ----------------------------------------------------------------
    # Attributes
    # ----------------------------------------------------------------

    def size(self):
        return self.p.n

    def chebyshev_coefficients(self):
        return self.chebpolyfit(self.values())

    def values(self):
        return self._values
        
    def domain(self):
        return self._domain        

    # ----------------------------------------------------------------
    # Integration and differentiation
    # ----------------------------------------------------------------

    def integrate(self):
        raise NotImplementedError()

    def differentiate(self):
        raise NotImplementedError()

    def dot(self, other):
        """
        Return the Hilbert scalar product $\int f.g$.
        """
        prod = self * other
        return prod.sum()

    def norm(self):
        """
        Return: square root of scalar product with itself.
        """
        norm = np.sqrt(self.dot(self))
        return norm


    # ----------------------------------------------------------------
    # Miscellaneous operations
    # ----------------------------------------------------------------
    def restrict(self,subinterval):
        """
        Return a chebfun that matches self on subinterval.
        """
        if ( len(subinterval) != 2 ) or ( subinterval[0] >= subinterval[1] ):
            raise ValueError(subinterval)
        if subinterval[0] < self._domain[0]:
            raise ValueError(subinterval[0],self._domain[0])
        if subinterval[1] > self._domain[1]:
            raise ValueError(subinterval[1],self._domain[1]) 
        return Chebfun.from_function(self, subinterval)


    # ----------------------------------------------------------------
    # Class method aliases
    # ----------------------------------------------------------------
    diff = differentiate
    cumsum = integrate
    
    # ----------------------------------------------------------------
    # Plotting Methods
    # ----------------------------------------------------------------

    plot_res = 1000

    def dimension_info(self):
        """
        Dimension information of the fun.
        """
        vals = self.values()
        # "local" degree of freedom; whether it is a complex or real fun
        t = vals.dtype.kind
        if t == 'c':
            dof = 2
        else:
            dof = 1
        # "global" degree of freedom: the dimension
        shape = np.shape(vals)
        if len(shape) == 1:
            dim = 1
        else:
            dim = shape[1]
        return dim, dof

    def plot_data(self):
        """
        Plot data depending on the dimension of the fun.
        """
        a, b = self.domain()
        ts = np.linspace(a, b, self.plot_res)
        values = self(ts)
        dim, dof = self.dimension_info()
        if 1 == dim and 1 == dof: # 1D real
            xs = ts
            ys = values
            xi = self._ui_to_ab(self.p.xi)
            yi = self.values()
            d = 1
        elif 2 == dim and 1 == dof: # 2D real
            xs = values[:, 0]
            ys = values[:, 1]
            xi = self._ui_to_ab(self.values()[:, 0])
            yi = self.values()[:, 1]
            d = 2
        elif 1 == dim and 2 == dof: # 1D complex
            xs = np.real(values)
            ys = np.imag(values)
            xi = self._ui_to_ab(np.real(self.values()))
            yi = np.imag(self.values())
            d = 2
        else:
            raise ValueError("Too many dimensions to plot")
        return xs, ys, xi, yi, d

    def plot(self, with_interpolation_points=False, *args, **kwargs):
        """
        Plot the fun with the additional arguments args, kwargs.
        """
        xs, ys, xi, yi, d = self.plot_data()
        axis = plt.gca()
        axis.plot(xs, ys, *args, **kwargs)
        if with_interpolation_points:
            current_color = axis.lines[-1].get_color() # figure out current colour
            axis.plot(xi, yi, marker='.', linestyle='', color=current_color)
        plt.plot()
        if 2 == d:
            axis.axis('equal')
        return axis

    def chebcoeffplot(self, *args, **kwds):
        """
        Plot the coefficients.
        """
        fig = plt.figure()
        ax  = fig.add_subplot(111)

        coeffs = self.chebyshev_coefficients()
        data = np.log10(np.abs(coeffs))
        ax.plot(data, 'r' , *args, **kwds)
        ax.plot(data, 'r.', *args, **kwds)

        return ax

    def plot_interpolation_points(self, *args, **kwargs):
        plt.plot(self._ui_to_ab(self.p.xi), self.values(), *args, **kwargs)

    def compare(self, f, *args, **kwds):
        """
        Plots the original function against its fun interpolant.
        
        INPUTS:

            -- f: Python, Numpy, or Sage function
        """
        a, b = self.domain()
        x = np.linspace(a, b, 10000)
        fig = plt.figure()
        ax = fig.add_subplot(211)
        
        ax.plot(x, f(x), '#dddddd', linewidth=10, label='Actual', *args, **kwds)
        label = 'Fun Interpolant (d={0})'.format(self.size())
        self.plot(color='red', label=label, *args, **kwds)
        ax.legend(loc='best')

        ax  = fig.add_subplot(212)
        ax.plot(x, abs(f(x)-self(x)), 'k')

        return ax



class Chebfun(Fun):
    """
    Eventually set this up so that a Chebfun is a collection of Funs. This 
    will enable piecewise smooth representations al la Matlab Chebfun v2.0.  
    """
    # ----------------------------------------------------------------
    # Standard construction class methods.
    # ----------------------------------------------------------------

    @classmethod
    def identity(self, domain=[-1., 1.]):
        """
        The Fun for the identity function x -> x.
        """
        return self.from_data([domain[1],domain[0]], domain)

    # (M.R) shouldn't this be a separate class/function? It's not 
    # specific to any particular instance of Fun.
    @classmethod
    def basis(self, n):
        """
        Chebyshev basis functions T_n.
        """
        if n == 0:
            return self(np.array([1.]))
        vals = np.ones(n+1)
        vals[1::2] = -1
        return self(vals)

    # ----------------------------------------------------------------
    # Integration and differentiation
    # ----------------------------------------------------------------

    def sum(self):
        """
        Evaluate the integral of the Fun over the given interval using
        Clenshaw-Curtis quadrature.
        """
        ak = self.chebyshev_coefficients()
        ak2 = ak[::2]
        n = len(ak2)
        Tints = 2/(1-(2*np.arange(n))**2)
        val = np.sum((Tints*ak2.T).T, axis=0)
        a_, b_ = self.domain()
        return 0.5*(b_-a_)*val

    def integrate(self):
        """
        Return the Fun representing the primitive of self over the domain. The 
        output starts at zero on the left-hand side of the domain.
        """
        coeffs = self.chebyshev_coefficients()
        a,b = self.domain()
        int_coeffs = 0.5*(b-a)*poly.chebyshev.chebint(coeffs)
        antiderivative = self.from_chebcoeff(int_coeffs,domain=self.domain()) 
        return antiderivative - antiderivative(a)

    def differentiate(self, n=1):
        """
        n-th derivative, default 1.      
        """
        ak = self.chebyshev_coefficients()
        a_, b_ = self.domain()
        for _ in range(n):
            ak = self.differentiator(ak)
        return self.from_chebcoeff((2./(b_-a_))**n*ak,domain=self.domain())
        
    # ----------------------------------------------------------------
    # Roots 
    # ----------------------------------------------------------------
    def roots(self):
        """
        Utilises Boyd's O(n^2) recursive subdivision algorithm. The chebfun
        is recursively subsampled until it is successfully represented to 
        machine precision by a sequence of piecewise interpolants of degree
        100 or less. A colleague matrix eigenvalue solve is then applied to 
        each of these pieces and the results are concatenated.
        
        See: 
        J. P. Boyd, Computing zeros on a real interval through Chebyshev 
        expansion and polynomial rootfinding, SIAM J. Numer. Anal., 40 (2002), 
        pp. 1666–1682.
        """
        if self.size() <= 100:  
            ak = self.chebyshev_coefficients()
            v = np.zeros_like(ak[:-1])
            v[1] = 0.5
            C1 = linalg.toeplitz(v) 
            C2 = np.zeros_like(C1)
            C1[0,1] = 1.
            C2[-1,:] = ak[:-1]
            C = C1 - .5/ak[-1] * C2
            eigenvalues = linalg.eigvals(C) 
            return np.sort(self._ui_to_ab(np.array([
                root.real for root in eigenvalues
                    if np.allclose(root.imag,0,atol=1e-10) 
                        and np.abs(root.real) <=1])))     
        else:
            # divide at a close-to-zero split-point
            split_point = self._ui_to_ab(0.0123456789)     
            return np.concatenate(
                (self.restrict([self._domain[0],split_point]).roots(),
                 self.restrict([split_point,self._domain[1]]).roots())
            )

    # ----------------------------------------------------------------
    # Interpolation and evaluation (go from values to coefficients)
    # ----------------------------------------------------------------

    @classmethod
    def interpolation_points(self, N):
        """
        N Chebyshev points in [-1, 1], boundaries included
        """
        if N == 1:
            return np.array([0.])
        return np.cos(np.arange(N)*np.pi/(N-1))

    @classmethod
    def sample_function(self, f, N):
        """
        Sample a function on N+1 Chebyshev points.
        """
        x = self.interpolation_points(N+1)
        return f(x)

    @classmethod
    def chebpolyfit(self, sampled):
        """
        Compute Chebyshev coefficients for values located on Chebyshev points.
        sampled: array; first dimension is number of Chebyshev points
        """
        asampled = np.asarray(sampled)
        if len(asampled) == 1:
            return asampled
        evened = even_data(asampled)
        coeffs = dct(evened)
        return coeffs

    @classmethod
    def chebpolyval(self, chebcoeff):
        """
        Compute the interpolation values at Chebyshev points.
        chebcoeff: Chebyshev coefficients
        """
        N = len(chebcoeff)
        if N == 1:
            return chebcoeff

        data = even_data(chebcoeff)/2
        data[0] *= 2
        data[N-1] *= 2

        fftdata = 2*(N-1)*fftpack.ifft(data, axis=0)
        complex_values = fftdata[:N]
        # convert to real if input was real
        if np.isrealobj(chebcoeff):
            values = np.real(complex_values)
        else:
            values = complex_values
        return values

    @classmethod
    def interpolator(self, x, values):
        """
        Returns a polynomial with vector coefficients which interpolates the values at the Chebyshev points x
        """
        # hacking the barycentric interpolator by computing the weights in advance
        p = Bary([0.])
        N = len(values)
        weights = np.ones(N)
        weights[0] = .5
        weights[1::2] = -1
        weights[-1] *= .5
        p.wi = weights
        p.xi = x
        p.set_yi(values)
        return p

    # ----------------------------------------------------------------
    # Helper for differentiation.
    # ----------------------------------------------------------------

    @classmethod
    def differentiator(self, A):
        """Differentiate a set of Chebyshev polynomial expansion 
           coefficients
           Originally from http://www.scientificpython.net/1/post/2012/04/chebyshev-differentiation.html
            + (lots of) bug fixing + pythonisation
           """
        m = len(A)
        SA = (A.T* 2*np.arange(m)).T
        DA = np.zeros_like(A)
        if m == 1: # constant
            return np.zeros_like(A[0:1])
        if m == 2: # linear
            return A[1:2,]
        DA[m-3:m-1,] = SA[m-2:m,]
        for j in range(m//2 - 1):
            k = m-3-2*j
            DA[k] = SA[k+1] + DA[k+2]
            DA[k-1] = SA[k] + DA[k+1]
        DA[0] = (SA[1] + DA[2])*0.5
        return DA

# ----------------------------------------------------------------
# General utilities
# ----------------------------------------------------------------
def same_domain(fun1,fun2):
    """
    Returns True if the domains of two Fun objects are the same.
    """
    return np.allclose(fun1.domain(),fun2.domain(),rtol=1e-14,atol=1e-14)
            
def even_data(data):
    """
    Construct Extended Data Vector (equivalent to creating an
    even extension of the original function)
    Return: array of length 2(N-1)
    For instance, [0,1,2,3,4] --> [0,1,2,3,4,3,2,1]
    """
    return np.concatenate([data, data[-2:0:-1]],)

def dct(data):
    """
    Compute DCT using FFT
    """
    N = len(data)//2
    fftdata     = fftpack.fft(data, axis=0)[:N+1]
    fftdata     /= N
    fftdata[0]  /= 2.
    fftdata[-1] /= 2.
    if np.isrealobj(data):
        data = np.real(fftdata)
    else:
        data = fftdata
    return data

# ----------------------------------------------------------------
# Add overloaded operators
# ----------------------------------------------------------------

def _add_operator(cls, op):
    def method(self, other):
        if not same_domain(self,other):
            raise self.DomainMismatch(self.domain(),other.domain())
        return self.from_function(
            lambda x: op(self(x).T, other(x).T).T, domain=self.domain(),)
    cast_method = cast_scalar(method)
    name = op.__name__
    cast_method.__name__ = name
    cast_method.__doc__ = "operator {}".format(name)
    setattr(cls, name, cast_method)

def __rdiv__(a, b):
    return b/a

for _op in [operator.__mul__, operator.__div__, operator.__pow__, __rdiv__]:
    _add_operator(Fun, _op)

# ----------------------------------------------------------------
# Add numpy ufunc delegates
# ----------------------------------------------------------------

def _add_delegate(ufunc, nonlinear=True):
    if nonlinear:
        def method(self):
            return self.from_function(lambda x: ufunc(self(x)), domain=self.domain())
    else:
        def method(self):
            return self.from_data(ufunc(self.values()))
    name = ufunc.__name__
    method.__name__ = name
    method.__doc__ = "delegate for numpy's ufunc {}".format(name)
    setattr(Fun, name, method)

# Following list generated from:
# https://github.com/numpy/numpy/blob/master/numpy/core/code_generators/generate_umath.py
for func in [np.arccos, np.arccosh, np.arcsin, np.arcsinh, np.arctan, np.arctanh, np.cos, np.sin, np.tan, np.cosh, np.sinh, np.tanh, np.exp, np.exp2, np.expm1, np.log, np.log2, np.log1p, np.sqrt, np.ceil, np.trunc, np.fabs, np.floor, ]:
    _add_delegate(func)
for func in [np.real, np.imag]:
    _add_delegate(func, nonlinear=False)


# ----------------------------------------------------------------
# General Aliases
# ----------------------------------------------------------------
## chebpts = interpolation_points

# ----------------------------------------------------------------
# Constructor inspired by the Matlab version
# ----------------------------------------------------------------

def chebfun(f=None, domain=[-1,1], N=None, chebcoeff=None,):
    """
    Create a Chebyshev polynomial approximation of the function $f$ on the interval :math:`[-1, 1]`.
    
    :param callable f: Python, Numpy, or Sage function
    :param int N: (default = None)  specify number of interpolating points
    :param np.array chebcoeff: (default = np.array(0)) specify the coefficients of a Fun
    """

    # Chebyshev coefficients
    if chebcoeff is not None:
        return Chebfun.from_chebcoeff(chebcoeff,domain)

    # another Fun instance
    if isinstance(f, Fun):
        return Chebfun.from_fun(f)

    # callable
    if hasattr(f, '__call__'):
        return Chebfun.from_function(f, domain, N)

    # from here on, assume that f is None, or iterable
    if np.isscalar(f):
        f = [f]

    try:
        iter(f) # interpolation values provided
    except TypeError:
        pass
    else:
        return Chebfun(f,domain)

    raise TypeError('Impossible to initialise the Fun object from an object of type {}'.format(type(f)))





