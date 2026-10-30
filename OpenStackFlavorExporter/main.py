from datetime import datetime
from fastapi import FastAPI, HTTPException
from pymemcache.client.base import Client as MemCachedClient
from pymemcache import serde

from OpenStackFlavorExporter.model import Flavor, ExtendedFlavor
from OpenStackFlavorExporter.openstack.resources import Resources


# disable MEMCACHE by default
MEMCACHE = False
# set CPU overprovisioning to 4 by default
CPU_OVERPROVISIONING = 4
# set empty whitelist by default
FLAVOR_WHITELIST = []
# set "DEPRECATED" as default blacklist entry
FLAVOR_BLACKLIST = ["DEPRECATED"]
# Flavor-to-Aggregate strict matching options
AGGRMATCHPROPS = ""
# set debug to false by default
DEBUG = False

def configure_memcache(enabled=True, host="127.0.0.1:11211", expire=300, prefix=""):
    """
    Configure memcache.
    :param enabled: Enabled memcached support, defaults to True
    :param host: memcached host as string "<ip>:<port>", defaults to "127.0.0.1:11211"
    :param expire : time in seconds after cache expires, default to 300
    :param prefix : optional memcached key prefix, default to ""
    :return: None
    """
    global MEMCACHE, MEMCACHEDHOST, MEMCACHEDCLIENT, MEMCACHEEXPIREAFTER, MEMCACHEDPREFIX # pylint: disable=global-variable-undefined
    MEMCACHE = enabled
    MEMCACHEDHOST = host
    MEMCACHEEXPIREAFTER = expire
    MEMCACHEDCLIENT = MemCachedClient(MEMCACHEDHOST, serde=serde.pickle_serde)
    MEMCACHEDPREFIX = prefix

def configure(cpu_overprovisioning=4, whitelist=[], blacklist=[], aggr_match_opts="", debug=False): # pylint: disable=dangerous-default-value
    """
    Configure filters for flavors.
    
    :param whitelist: list of flavor names to be whitelisted. A name could be regular expression.
    :param blacklist: list of flavor names to be blacklisted. A name could be regular expression.
    :return: None
    """
    global CPU_OVERPROVISIONING, FLAVOR_WHITELIST, FLAVOR_BLACKLIST, AGGRMATCHPROPS, DEBUG  # pylint: disable=global-statement
    CPU_OVERPROVISIONING = cpu_overprovisioning
    FLAVOR_WHITELIST = whitelist
    FLAVOR_BLACKLIST = blacklist
    AGGRMATCHPROPS = aggr_match_opts
    DEBUG = debug

def update_cache():
    """
    Update memcache, if enabled.
    """
    global CPU_OVERPROVISIONING, FLAVOR_WHITELIST, FLAVOR_BLACKLIST, AGGRMATCHPROPS, DEBUG # pylint: disable=global-variable-undefined

    resources = Resources(cpu_overprovisioning=CPU_OVERPROVISIONING, whitelist=FLAVOR_WHITELIST,blacklist=FLAVOR_BLACKLIST,aggr_match_opts=AGGRMATCHPROPS,debug=DEBUG)

    try:
        resources.update()
        flavors = resources.get_flavors()
    finally:
        resources.close()

    if MEMCACHE:
        timestamp = datetime.now()
        # calculate available flavors
        # and cache them using memcache (if enabled)
        MEMCACHEDCLIENT.set(MEMCACHEDPREFIX+"Flavor", flavors, MEMCACHEEXPIREAFTER)
        MEMCACHEDCLIENT.set(MEMCACHEDPREFIX+"Flavor.timestamp", timestamp.strftime('%Y-%m-%d %H:%M:%S'), MEMCACHEEXPIREAFTER)

def _get_flavors() -> list[ExtendedFlavor]:
    """
    Get list of flavors. Use memcache to cache request if enabled.
    
    :return: List of Flavors
    :rtype: list[ExtendedFlavor]
    """

    flavors =  []
    timestamp = datetime.now()

    # ask cache first (if enabled)
    if MEMCACHE:
        flavors = MEMCACHEDCLIENT.get(MEMCACHEDPREFIX+'Flavor')
        if MEMCACHEDCLIENT.get(MEMCACHEDPREFIX+'Flavor.timestamp'):
            timestamp = datetime.strptime(MEMCACHEDCLIENT.get(MEMCACHEDPREFIX+'Flavor.timestamp'), '%Y-%m-%d %H:%M:%S')

    if not flavors:
        # calculate available flavors
        resources = Resources(cpu_overprovisioning=CPU_OVERPROVISIONING, whitelist=FLAVOR_WHITELIST,blacklist=FLAVOR_BLACKLIST,aggr_match_opts=AGGRMATCHPROPS,debug=DEBUG)
        try:
            resources.update()
            flavors = resources.get_flavors()
        finally:
            resources.close()

        # and cache them using memcache (if enabled)
        if MEMCACHE:
            MEMCACHEDCLIENT.set(MEMCACHEDPREFIX+"Flavor", flavors, MEMCACHEEXPIREAFTER)
            MEMCACHEDCLIENT.set(MEMCACHEDPREFIX+"Flavor.timestamp", timestamp.strftime('%Y-%m-%d %H:%M:%S'), MEMCACHEEXPIREAFTER)
    return flavors

tags_metadata = [
    {
        "name": "legacy",
        "description": "Legacy API endpoint."
    }
]
app = FastAPI(openapi_tags=tags_metadata)

@app.get("/gpus/flavors/",tags=["legacy"])
async def get_gpu_flavors() -> list[Flavor]:
    """
    Return a  list  of GPU flavors  (type equals "gpu"), or an empty 
    list in case that no FPU flavor is available.
    
    :return: List of GPU flavors
    :rtype: list[Flavor]
    """
    gpu_flavors = []
    for flavor in _get_flavors():
        if flavor.type == "gpu":
            gpu_flavors.append(flavor)
    return gpu_flavors

@app.get("/gpus/flavor/{item_id}", tags=["legacy"])
async def get_gpu_flavor(item_id) -> Flavor:
    """
    Return a GPU flavor with given id
    
    :param item_id: id of GPU flavor to be returned
    :return: GPU Flavor
    :rtype: Flavor
    """
    for flavor in _get_flavors():
        if flavor.type == "gpu" and flavor.id == item_id:
            return flavor
    raise HTTPException(status_code=404, detail="Item not found")

@app.get("/v2/flavors/")
async def get_flavors() -> list[ExtendedFlavor]:
    """
    Return a list of flavors.
    
    :return: list of flavors
    :rtype: list[ExtendedFlavor]
    """
    return _get_flavors()

@app.get("/v2/flavor/{item_id}")
async def get_flavor(item_id) -> ExtendedFlavor:
    """
    Return a flavor with given id.

    :param item_id: id of flavors to be returned
    :return: Flavor
    :rtype: ExtendedFlavor
    """
    for flavor in _get_flavors():
        if flavor.id == item_id:
            return flavor
    raise HTTPException(status_code=404, detail="Item not found")
