# -*- coding: utf-8 -*-
# Copyright (c) 2013, Vispy Development Team.
# Distributed under the (new) BSD License. See LICENSE.txt for more info.

""" Definition of Texture class.

This code is inspired by similar classes from Visvis and Pygly.

"""

# todo: implement ext_available
# todo: make a Texture1D that makes a nicer interface to a 2D texture
# todo: same for Texture3D?
# todo: Cubemap texture
# todo: mipmapping, allow creating mipmaps
# todo: compressed textures?


from __future__ import print_function, division, absolute_import

import sys
import numpy as np

from vispy import gl
from vispy.util.six import string_types
from . import GLObject, ext_available



class TextureError(RuntimeError):
    """ Raised when something goes wrong that depens on state that was set 
    earlier (due to deferred loading).
    """
    pass


class Texture(GLObject):
    """ Representation of an OpenGL texture. 
    
    """
    
    # Dict that maps numpy datatypes to openGL ES 2.0 data types
    # We use strings to be more failsafe; e.g. np.float128 does not always exist
    DTYPE2GTYPE = { 'uint8': gl.GL_UNSIGNED_BYTE,
                    'float16': gl.ext.GL_HALF_FLOAT, # Needs GL_OES_texture_half_float
                    'float32': gl.GL_FLOAT,  # Needs GL_OES_texture_float
            }
    
    
    def __init__(self, target, data=None, format=None, clim=None):
        GLObject.__init__(self)
        
        # Store target (i.e. the texture type)
        if target not in [gl.GL_TEXTURE_2D, gl.ext.GL_TEXTURE_3D]:
            raise ValueError('Unsupported target "%r"' % target)
        self._target = target
        
        # A reference to pending data to set
        self._pending_data = None
        self._texture_shape = None
        
        # Each subdata that is set gets processed
        self._pending_subdata = []
        
        # The parameters that apply to this texture. One variable to 
        # keep track of pending parameters, the other for resetting
        # parameters if its re-uploaded.
        self._texture_params = {}
        self._pending_params = {}
        
        # Set default parameters for min and mag filter, otherwise an
        # image is not shown by default, since the default min_filter
        # is GL_NEAREST_MIPMAP_LINEAR
        # Note that mipmapping is not allowed unless the texture_npot
        # extension is available.
        self.set_filter(gl.GL_LINEAR, gl.GL_LINEAR)
        
        # Set default parameter for clamping. CLAMP_TO_EDGE since that
        # is required if a texture is used as a render target.
        # Also, in OpenGL ES 2.0, wrapping must be CLAMP_TO_EDGE if 
        # textures are not a power of two, unless the texture_npot extension
        # is available.
        if self._target == gl.ext.GL_TEXTURE_3D:
            self.set_wrapping(gl.GL_CLAMP_TO_EDGE, gl.GL_CLAMP_TO_EDGE,
                                            gl.GL_CLAMP_TO_EDGE)
        else:
            self.set_wrapping(gl.GL_CLAMP_TO_EDGE, gl.GL_CLAMP_TO_EDGE)
        
        # Set data?
        if data is None:
            pass
        elif isinstance(data, np.ndarray):
            self.set_data(data, format=format, clim=clim)
        elif isinstance(data, tuple):
            self.set_storage(data, format=format)
        else:
            raise ValueError('Invalid value to initialize Texture with.')
    
    
    def set_filter(self, mag_filter, min_filter):
        """ Set interpolation filters. EIther parameter can be None to 
        not (re)set it.
        
        Parameters
        ----------
        mag_filter : GL_ENUM or string
            The magnification filter (when texels are larger than screen
            pixels). Can be GL_NEAREST, GL_LINEAR. 
        min_filter : GL_ENUM or string
            The minification filter (when texels are smaller than screen 
            pixels). For this filter, mipmapping can be applied to perform
            antialiasing (if mipmaps are available for this texture).
            Can be GL_NEAREST, GL_LINEAR, GL_NEAREST_MIPMAP_NEAREST,
            GL_NEAREST_MIPMAP_LINEAR, GL_LINEAR_MIPMAP_NEAREST,
            GL_LINEAR_MIPMAP_LINEAR.
        """
        # Allow strings
        mag_filter = self._string_to_enum(mag_filter)
        min_filter = self._string_to_enum(min_filter)
        # Check
        assert mag_filter in (None, gl.GL_NEAREST, gl.GL_LINEAR)
        assert min_filter in (None, gl.GL_NEAREST, gl.GL_LINEAR, 
                    gl.GL_NEAREST_MIPMAP_NEAREST, gl.GL_NEAREST_MIPMAP_LINEAR,
                    gl.GL_LINEAR_MIPMAP_NEAREST, gl.GL_LINEAR_MIPMAP_LINEAR)
        
        # Set 
        if mag_filter is not None:
            self._pending_params[gl.GL_TEXTURE_MAG_FILTER] = mag_filter
            self._texture_params[gl.GL_TEXTURE_MAG_FILTER] = mag_filter
        if min_filter is not None:
            self._pending_params[gl.GL_TEXTURE_MIN_FILTER] = min_filter
            self._texture_params[gl.GL_TEXTURE_MIN_FILTER] = min_filter
        
        self._need_update = True
    
    
    def set_wrapping(self, wrapx, wrapy, wrapz=None):
        """ Set texture coordinate wrapping. 
        
        Parameters
        ----------
        wrapx : GL_ENUM or string
            The wrapping mode in the x-direction. Can be GL_REPEAT,
            GL_CLAMP_TO_EDGE, GL_MIRRORED_REPEAT.
        wrapy : GL_ENUM or string
            Dito for y.
        wrap z : GL_ENUM or string
            Dito for z. Only makes sense for 3D textures, and requires
            the texture_3d extension. Optional.
        """
        # Allow strings
        wrapx = self._string_to_enum(wrapx)
        wrapy = self._string_to_enum(wrapy)
        wrapz = self._string_to_enum(wrapz)
        # Check
        assert wrapx in (None, gl.GL_REPEAT, gl.GL_CLAMP_TO_EDGE, gl.GL_MIRRORED_REPEAT)
        assert wrapy in (None, gl.GL_REPEAT, gl.GL_CLAMP_TO_EDGE, gl.GL_MIRRORED_REPEAT)
        assert wrapz in (None, gl.GL_REPEAT, gl.GL_CLAMP_TO_EDGE, gl.GL_MIRRORED_REPEAT)
        
        # Set 
        if wrapx is not None:
            self._pending_params[gl.GL_TEXTURE_WRAP_S] = wrapx
            self._texture_params[gl.GL_TEXTURE_WRAP_S] = wrapx
        if wrapy is not None:
            self._pending_params[gl.GL_TEXTURE_WRAP_T] = wrapy
            self._texture_params[gl.GL_TEXTURE_WRAP_T] = wrapy
        if wrapz is not None:
            self._pending_params[gl.ext.GL_TEXTURE_WRAP_R] = wrapz
            self._texture_params[gl.ext.GL_TEXTURE_WRAP_R] = wrapz
        
        self._need_update = True
    
    
    def _string_to_enum(self, param):
        """ Convert a string to a GL enum.
        """
        if isinstance(param, string_types):
            param = param.upper()
            if not param.startswith('GL'):
                param = 'GL_' + param
            param = getattr(gl, param)
        return param
    
    
    def set_subdata(self, offset, data, level=0, format=None, clim=None):
        """ Set a region of data for this texture. This method can be
        called at any time (even if there is no context yet). 
        
        In contrast to set_data(), each call to this method results in
        an OpenGL api call.
        
        Parameters
        ----------
        offset : tuple
            The offset for each dimension, to update part of the texture.
        data : numpy array
            The texture data to set. The data (with offset) cannot exceed
            the boundaries of the current texture.
        level : int
            The mipmap level. Default 0.
        format : OpenGL enum
            The format representation of the data. If not given or None,
            it is decuced from the given data. Can be GL_RGB, GL_RGBA,
            GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_ALPHA.
        clim : (min, max)
            Contrast limits for the data. If specified, min will end
            up being 0.0 (black) and max will end up as 1.0 (white).
            If not given or None, clim is determined automatically. For
            floats they become (0.0, 1.0). For integers the are mapped to
            the full range of the type. 
        
        """
        
        # Is there data?
        if self._texture_shape is None:
            raise RuntimeError('Cannot set subdata if there is not data or storage yet.')
        
        # Get ndim
        MAP = {gl.GL_TEXTURE_2D:2, gl.ext.GL_TEXTURE_3D:3}
        ndim = MAP.get(self._target, 0)
        
        # Check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        shape = data.shape
        assert isinstance(shape, tuple)
        assert len(shape) in (ndim, ndim+1)
        
        # Check offset
        offset = [int(i) for i in offset]
        assert len(offset) == ndim
        
        # Check level, format, clim
        assert isinstance(level, int) and level >= 0
        assert format in (None, gl.GL_RGB, gl.GL_RGBA, gl.GL_LUMINANCE, 
                            gl.GL_LUMINANCE_ALPHA, gl.GL_ALPHA)
        assert clim is None or (isinstance(clim, tuple) and len(clim)==2)
        
        # Set pending data ...
        self._pending_subdata.append((data, offset, level, format, clim))
        self._need_update = True
    
    
    def set_data(self, data, level=0, format=None, clim=None):
        """ Set the data for this texture. This method can be called at any
        time (even if there is no context yet).
        
        It is relatively cheap to call this function multiple times,
        only the last data is set right before drawing. If the shape
        of the given data matches the shape of the current texture, the
        data is updated in a fast manner.
        
        Parameters
        ----------
        data : numpy array
            The texture data to set.
        level : int
            The mipmap level. Default 0.
        format : OpenGL enum
            The format representation of the data. If not given or None,
            it is decuced from the given data. Can be GL_RGB, GL_RGBA,
            GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_ALPHA.
        clim : (min, max)
            Contrast limits for the data. If specified, min will end
            up being 0.0 (black) and max will end up as 1.0 (white).
            If not given or None, clim is determined automatically. For
            floats they become (0.0, 1.0). For integers the are mapped to
            the full range of the type. 
        
        """
        
        # Get ndim
        MAP = {gl.GL_TEXTURE_2D:2, gl.ext.GL_TEXTURE_3D:3}
        ndim = MAP.get(self._target, 0)
        
        # Check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        shape = data.shape
        assert isinstance(shape, tuple)
        assert len(shape) in (ndim, ndim+1)
        
        # Check level, format, clim
        assert isinstance(level, int) and level >= 0
        assert format in (None, gl.GL_RGB, gl.GL_RGBA, gl.GL_LUMINANCE, 
                            gl.GL_LUMINANCE_ALPHA, gl.GL_ALPHA)
        assert clim is None or (isinstance(clim, tuple) and len(clim)==2)
        
        # Clear subdata
        self._pending_subdata = []
        
        # Set pending data ...
        self._pending_data = data, None, level, format, clim
        self._texture_shape = data.shape
        self._need_update = True
    
    
    def set_storage(self, shape, level=0, format=None):
        """ Allocate storage for this texture. This is useful if the texture
        is used as a render target for an FBO. 
        
        A call that only uses the shape argument does not result in an
        action if the call would not change the shape.
        
        Parameters
        ----------
        shape : tuple
            The shape of the "virtual" data. By specifying e.g. (20,20,3) for
            a Texture2D, one implicitly sets the format to GL_RGB. Note
            that shape[0] is height.
        level : int
            The mipmap level. Default 0.
        format : OpenGL enum
            The format representation of the data. If not given or None,
            it is decuced from the given data. Can be GL_RGB, GL_RGBA,
            GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_ALPHA.
        """
        
        # Get ndim
        MAP = {gl.GL_TEXTURE_2D:2, gl.ext.GL_TEXTURE_3D:3}
        ndim = MAP.get(self._target, 0)
        
        # Is this already my shape?
        if format is None and level==0 and self._texture_shape is not None:
            if self._texture_shape[:ndim] == shape[:ndim]:
                return
        
        # Check shape
        assert isinstance(shape, tuple)
        assert len(shape) in (ndim, ndim+1)
        shape = tuple([int(i) for i in shape])
        assert all([i>0 for i in shape])
        
        # Check level, format, clim
        assert isinstance(level, int) and level >= 0
        assert format in (None, gl.GL_RGB, gl.GL_RGBA, gl.GL_LUMINANCE, 
                            gl.GL_LUMINANCE_ALPHA, gl.GL_ALPHA)
        
        # Set pending data ...
        self._pending_data = shape, None, level, format, None
        self._texture_shape = shape
        self._need_update = True
    
    
    def _create(self):
        self._handle = gl.glGenTextures(1)
    
    
    def _delete(self):
        gl.glDeleteTextures([self._handle])
    
    
    def _activate(self):
        gl.glBindTexture(self._target, self._handle)
    
    
    def _deactivate(self):
        gl.glBindTexture(self._target, 0)
    
    
    def _update(self):
        
        # If we use a 3D texture, we need an extension
        if self._target == gl.ext.GL_TEXTURE_3D:
            if not ext_available('GL_texture_3D'):
                raise TextureError('3D Texture not available.')
        
        # Need to update data?
        if self._pending_data:
            pendingData, self._pending_data = self._pending_data, None
            # Process pending data
            self._process_pending_data(*pendingData)
            # If not ok, warn (one time)
            if not gl.glIsTexture(self._handle):
                self._handle = 0
                print('Warning enabling texture, the texture is not valid.')
                return
        
        # Need to update some regions?
        while self._pending_subdata:
            pendingData = self._pending_subdata.pop(0)
            # Process pending data
            self._process_pending_data(*pendingData)
        
        # Check
        if not gl.glIsTexture(self._handle): 
            raise TextureError('This should not happen (texture is invalid)')
        
        # Need to update any parameters?
        self._activate()
        while self._pending_params:
            param, value = self._pending_params.popitem()
            gl.glTexParameter(self._target, param, value)
    
    
    def _process_pending_data(self, data, offset, level, format, clim):
        """ Process the pending data. Uploading the data (i.e. create
        a new texture) or updating it (a subsection).
        """
        
        if isinstance(data, np.ndarray):
            # Convert data type to one supported by OpenGL
            data = convert_data(data, clim)
            # Set shape
            shape = data.shape
            
            # If data is of same shape as current texture, update is much faster
            if not offset:
                MAP = {gl.GL_TEXTURE_2D:2, gl.ext.GL_TEXTURE_3D:3}
                ndim = MAP.get(self._target, 0)
                if data.shape == self._texture_shape and self._valid:
                    offset = [0 for i in self._texture_shape[:ndim]]
        
        elif isinstance(data, tuple):
            # Set shape
            shape = data
        else:
            raise TextureError('data is not a valid type, should not happen!')
        
        # Determine format (== internalformat) 
        if format is None:
            format = get_format(shape, self._target)
        
        if offset:
            # Update: fast!
            gl.glBindTexture(self._target, self._handle)
            if self._handle <= 0 or not gl.glIsTexture(self._handle):
                raise TextureError('Cannot update texture if there is no texture.')
            self._upload_subdata(data, offset, format, level)
            
        else:
            # (re)upload: slower
            if self._valid:
                # We delete the existing texture first. In theory this
                # should not be necessary, but some implementations cause
                # memory leaks otherwise.
                self.delete() 
                self._create()
            # Upload!
            self._activate()
            if isinstance(data, tuple):
                self._allocate_storage(shape, format, level)
            else:
                self._upload_data(data, format, level)
            # Set all parameters that the user set
            for param, value in self._texture_params.items():
               gl.glTexParameter(self._target, param, value)
            self._pending_params = {} # We just applied all 
    
    
    def _allocate_storage(self, shape, format, level=0):
        """ Allocate space for the current texture object. 
        It should have been verified that the texture will fit.
        """
        # Determine function and target from texType
        D = {   #gl.GL_TEXTURE_1D: (gl.glTexImage1D, 1),
                gl.GL_TEXTURE_2D: (gl.glTexImage2D, 2),
                gl.ext.GL_TEXTURE_3D: (gl.ext.glTexImage3D, 3)}
        uploadFun, ndim = D[self._target]
        
        # Determine type
        gltype = gl.GL_UNSIGNED_BYTE
        
        # Build args list
        size = size = [i for i in reversed( shape[:ndim] )]
        args = [self._target, level, format] + size + [0, format, gltype, None]
        
        # Call
        uploadFun(*tuple(args))
    
    
    def _upload_data(self, data, format, level=0):
        """ Upload a texture to the current texture object. 
        It should have been verified that the texture will fit.
        """
        # Determine function and target from texType
        D = {   #gl.GL_TEXTURE_1D: (gl.glTexImage1D, 1),
                gl.GL_TEXTURE_2D: (gl.glTexImage2D, 2),
                gl.ext.GL_TEXTURE_3D: (gl.ext.glTexImage3D, 3)}
        uploadFun, ndim = D[self._target]
        
        # Determine type
        thetype = data.dtype.name
        if not thetype in self.DTYPE2GTYPE: # Note that we convert if necessary in Texture
            raise TextureError("Cannot translate datatype %s to GL." % thetype)
        gltype = self.DTYPE2GTYPE[thetype]
        
        # Build args list
        size, gltype = self._get_size_and_type(data, ndim)
        args = [self._target, level, format] + size + [0, format, gltype, data]
        
        # Check the alignment of the texture
        alignment = self._get_alignment(data.shape[-1])
        if alignment != 4:
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, alignment)
        
        # Call
        uploadFun(*tuple(args))
        
        # Check if we need to reset our pixel store state
        if alignment != 4:
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
    
    
    def _upload_subdata(self, data, offset, format, level=0):
        """ Update an existing texture object.
        """
        # Determine function and target from texType
        D = {   #gl.GL_TEXTURE_1D: (gl.glTexSubImage1D, 1),
                gl.GL_TEXTURE_2D: (gl.glTexSubImage2D, 2),
                gl.ext.GL_TEXTURE_3D: (gl.ext.glTexSubImage3D, 3)}
        uploadFun, ndim = D[self._target]
        
        # Build argument list
        size, gltype = self._get_size_and_type(data, ndim)
        offset = offset[::-1] #[i for i in offset]
        assert len(offset) == len(size)
        args = [self._target, level] + offset + size + [format, gltype, data]
        
        # Upload!
        uploadFun(*tuple(args))
    
    
    def _get_size_and_type(self, data, ndim):
        # Determine size
        #size = [i for i in reversed( data.shape[:ndim] )]
        size = [i for i in reversed( data.shape[:ndim] )]
        # Determine type
        thetype = data.dtype.name
        if not thetype in self.DTYPE2GTYPE: # Note that we convert if necessary in Texture
            raise TextureError("Cannot translate datatype %s to GL." % thetype)
        gltype = self.DTYPE2GTYPE[thetype]
        # Done
        return size, gltype
    
    
    # from pylgy
    def _get_alignment(self, width):
        """Determines a textures byte alignment.
    
        If the width isn't a power of 2
        we need to adjust the byte alignment of the image.
        The image height is unimportant
    
        http://www.opengl.org/wiki/Common_Mistakes#Texture_upload_and_pixel_reads
        """
        
        # we know the alignment is appropriate
        # if we can divide the width by the
        # alignment cleanly
        # valid alignments are 1,2,4 and 8
        # put 4 first, since it's the default
        alignments = [4,8,2,1]
        for alignment in alignments:
            if width % alignment == 0:
                return alignment
        


class Texture2D(Texture):
    """ Representation of a 2D texture. Inherits Texture.
    """
    def __init__(self, *args, **kwargs):
        Texture.__init__(self, gl.GL_TEXTURE_2D, *args, **kwargs)



class Texture3D(Texture):
    """ Representation of a 3D texture. Note that for this the
    GL_texture_3D extension needs to be available. Inherits Texture.
    """
    def __init__(self, *args, **kwargs):
        Texture.__init__(self, gl.ext.GL_TEXTURE_3D, *args, **kwargs)



class TextureCubeMap(Texture):
    """ Representation of a cube map, to store texture data for the
    6 sided of a cube. Used for instance to create environment mappings.
    
    This class is not yet implemented.
    """
    # Note that width and height for these textures should be equal
    def __init__(self, *args, **kwargs):
        raise NotImplementedError()
        Texture.__init__(self, gl.GL_TEXTURE_CUBE_MAP, *args, **kwargs)



## Utility functions


def get_format(shape, target):
    """ Get format, based on the target and the shape. If the shape
    does not match with the texture type, an exception is raised.
    The only format that cannot be deduced from the shape is GL_ALPHA
    """
    
    if target == gl.GL_TEXTURE_2D:
        if len(shape)==2:
            format = gl.GL_LUMINANCE              
        elif len(shape)==3 and shape[2]==1:
            format = gl.GL_LUMINANCE
        elif len(shape)==3 and shape[2]==2:
            format = gl.GL_LUMINANCE_ALPHA
        elif len(shape)==3 and shape[2]==3:
            format = gl.GL_RGB
        elif len(shape)==3 and shape[2]==4:
            format = gl.GL_RGBA
        else:
            raise TextureError("Cannot determine format: data of invalid shape.")
    
    elif target == gl.ext.GL_TEXTURE_3D:
        if len(shape)==3:
            format = gl.GL_LUMINANCE
        elif len(shape)==4 and shape[3]==1:
            format = gl.GL_LUMINANCE
        elif len(shape)==4 and shape[3]==2:
            format = gl.GL_LUMINANCE_ALPHA
        elif len(shape)==4 and shape[3]==3:
            format = gl.GL_RGB
        elif len(shape)==4 and shape[3]==4:
            format = gl.GL_RGBA
        else:
            raise TextureError("Cannot determine format: data of invalid shape.")
    
    else:
        raise TextureError("Cannot determine format with these dimensions.")
    
    return format


def convert_data(data, clim=None):
    """ Convert data to a type that OpenGL can deal with.
    Also applies contrast limits if given.
    """
    
    # Prepare
    FLOAT32_SUPPORT = ext_available('texture_float')
    FLOAT16_SUPPORT = ext_available('texture_half_float')
    CONVERTING = False
    
    # Determine clim if not given, copy or make float32 if necessary.
    # Copies may be necessary because following operations are in-place.
    if data.dtype.name == 'bool':
        # Bools are ... unsigned ints
        data = data.astype(np.uint8)
        clim = None
    elif data.dtype.name == 'uint8':
        # Uint8 is what we need! If clim is None, no action required
        if clim is not None:
            data = data.astype(np.float32)
    elif data.dtype.name == 'float16':
        # Float16 may be allowed. If clim is None, no action is required
        if clim is not None:
            data = data.copy()
        elif not FLOAT16_SUPPORT:
            CONVERTING = True
            data = data.copy()
    elif data.dtype.name == 'float32':
        # Float32 may be allowed. If clim is None, no action is required
        if clim is not None:
            data = data.copy()
        elif not FLOAT32_SUPPORT:
            CONVERTING = True
            data = data.copy()
    elif 'float' in data.dtype.name:
        # All other floats are converted with relative ease
        CONVERTING = True
        data = data.astype(np.float32)
    elif data.dtype.name.startswith('int'):
        # Integers, we need to parse the dtype
        CONVERTING = True
        if clim is None:
            max = 2**int(data.dtype.name[3:])
            clim = -max//2, max//2-1
        data = data.astype(np.float32)
    elif data.dtype.name.startswith('uint'):
        # Unsigned integers, we need to parse the dtype
        CONVERTING = True
        if clim is None:
            max = 2**int(data.dtype.name[4:])
            clim = 0, max//2
        data = data.astype(np.float32)
    else:
        raise TextureError('Could not convert data type %s.' % data.dtype.name)
    
    # Apply limits if necessary
    if clim is not None:
        assert isinstance(clim, tuple)
        assert len(clim) == 2
        if clim[0] != 0.0:
            data -= clim[0]
        if clim[1]-clim[0] != 1.0:
            data *= 1.0 / (clim[1]-clim[0])
    
    #if CONVERTING:
    #    print('Warning, converting data.')
    
    # Convert if necessary
    if data.dtype == np.uint8:
        pass  # Always possible
    elif data.dtype == np.float16 and FLOAT16_SUPPORT:
        pass  # Yeah
    elif data.dtype == np.float32 and FLOAT32_SUPPORT:
        pass  # Yeah
    elif data.dtype in (np.float16, np.float32):
        # Arg, convert. Don't forget to clip
        data *= 256.0
        data[data<0.0] = 0.0
        data[data>256.0] = 256.0
        data = data.astype(np.uint8)
    else:
        raise TextureError('Error converting data type. This should not happen.')
    
    # Done
    return data
