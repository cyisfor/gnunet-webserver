from sys import argv
from ctypes import CDLL,c_void_p,c_int,c_char_p,c_size_t


libmagic=None
try:
	libmagic=CDLL("libmagic.so") #or even better, check ctypes.util
except ImportError:
	exit(1)

MAGIC_NONE=0x000000 				# No flags 
MAGIC_DEBUG=0x000001 				# Turn on debugging 
MAGIC_SYMLINK=0x000002 				# Follow symlinks 
MAGIC_COMPRESS=0x000004				# Check inside compressed files 
MAGIC_DEVICES=0x000008	 			# Look at the contents of devices 
MAGIC_MIME_TYPE=0x000010			# Return only the MIME type 
MAGIC_CONTINUE=0x000020 			# Return all matches 
MAGIC_CHECK=0x000040 				# Print warnings to stderr 
MAGIC_PRESERVE_ATIME=0x000080		# Restore access time on exit 
MAGIC_RAW=0x000100					# Don't translate unprint chars 
MAGIC_ERROR=0x000200 				# Handle ENOENT etc as real errors 
MAGIC_MIME_ENCODING=0x000400 		# Return only the MIME encoding 
MAGIC_MIME=(MAGIC_MIME_TYPE|MAGIC_MIME_ENCODING)
MAGIC_NO_CHECK_COMPRESS=0x001000 	# Don't check for compressed files 
MAGIC_NO_CHECK_TAR=0x002000 		# Don't check for tar files 
MAGIC_NO_CHECK_SOFT=0x004000 		# Don't check magic entries 
MAGIC_NO_CHECK_APPTYPE=0x008000		# Don't check application type 
MAGIC_NO_CHECK_ELF=0x010000			# Don't check for elf details 
MAGIC_NO_CHECK_ASCII=0x020000 		# Don't check for ascii files 
MAGIC_NO_CHECK_TOKENS=0x100000 		# Don't check ascii/tokens 

# Defined for backwards compatibility; do nothing 
MAGIC_NO_CHECK_FORTRAN=0x000000 	# Don't check ascii/fortran 
MAGIC_NO_CHECK_TROFF=0x000000 	    # Don't check ascii/troff 


#typedef struct magic_set *magic_t;
#magic_t magic_open(int);
#void magic_close(magic_t);

#const char *magic_file(magic_t, const char *);
#const char *magic_descriptor(magic_t, int);
#const char *magic_buffer(magic_t, const void *, size_t);

#const char *magic_error(magic_t);
#int magic_setflags(magic_t, int);

#int magic_load(magic_t, const char *);
#int magic_compile(magic_t, const char *);
#int magic_check(magic_t, const char *);
#int magic_errno(magic_t);



magic_t=c_void_p #void pointer.

magic_open=libmagic.magic_open
magic_open.restype=magic_t
magic_open.argtypes=[c_int]


magic_close=libmagic.magic_close
magic_close.restype=None
magic_close.argtypes=[magic_t]

magic_file=libmagic.magic_file
magic_file.restype=c_char_p
magic_file.argtypes=[magic_t, c_char_p]

magic_descriptor=libmagic.magic_descriptor
magic_descriptor.restype=c_char_p
magic_descriptor.argtypes=[magic_t, c_int]

magic_buffer=libmagic.magic_buffer
magic_buffer.restype=c_char_p
magic_buffer.argtypes=[magic_t, c_char_p, c_size_t]

magic_error=libmagic.magic_error
magic_error.restype=c_char_p
magic_error.argtypes=[magic_t]

magic_setflags=libmagic.magic_setflags
magic_setflags.restype=c_int
magic_setflags.argtypes=[magic_t, c_int]

magic_load=libmagic.magic_load
magic_load.restype=c_int
magic_load.argtypes=[magic_t, c_char_p]

magic_compile=libmagic.magic_compile
magic_compile.restype=c_int
magic_compile.argtypes=[magic_t, c_char_p]

magic_check=libmagic.magic_check
magic_check.restype=c_int
magic_check.argtypes=[magic_t, c_char_p]

magic_errno=libmagic.magic_errno
magic_errno.restype=c_int
magic_errno.argtypes=[magic_t]

def errcheck(result, func, args):
    err=magic_error(args[0])
    if err is None:
        return result
    raise Exception

for f in (magic_buffer, magic_check, magic_close, magic_descriptor, magic_file, magic_load):
    f.errcheck=errcheck    


def guess(filepath):
	mc=magic_open(MAGIC_NONE)
	magic_load(mc, None)
	res=magic_file(mc, filepath)
	magic_close(mc)
	return res
