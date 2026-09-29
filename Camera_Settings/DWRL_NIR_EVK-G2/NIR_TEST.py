#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun 15 13:35:09 2026

@author: admin
"""

from mvIMPACT import acquire

dm = acquire.DeviceManager()

for i in range(dm.deviceCount()):
    d = dm.getDevice(i)
    print(i, d.serial.read(), d.product.read())

#%%
from mvIMPACT import acquire
import ctypes
# Device manager
dev_mgr = acquire.DeviceManager()
print(f"Found {dev_mgr.deviceCount()} device(s)")
#%%
for i in range(dev_mgr.deviceCount()):
    dev = dev_mgr.getDevice(i)
    print(
        f"[{i}] "
        f"Serial={dev.serial.read()} "
        f"Product={dev.product.read()} "
        f"Family={dev.family.read()}"
    )
#%%
if dev_mgr.deviceCount() == 0:
    raise RuntimeError("No camera found!")

# Open first camera
dev = dev_mgr.getDevice(1)
dev.open()

fi = acquire.FunctionInterface(dev)

# Request one image
request_nr = fi.imageRequestSingle()

if not fi.imageRequestWaitFor(5000):
    raise RuntimeError("Timeout waiting for image")

request = fi.getRequest(request_nr)

if not request.isOK:
    raise RuntimeError(
        f"Image request failed: {request.requestResult.readS()}"
    )

width = request.imageWidth.read()
height = request.imageHeight.read()
channels = request.imageChannelCount.read()

print(f"Image: {width} x {height}, channels={channels}")

# Access image buffer
buf = ctypes.string_at(
    request.imageData.read(),
    request.imageSize.read()
)

print("First 32 bytes:")
print(list(buf[:32]))

fi.imageRequestUnlock(request_nr)

dev.close()

#%%
from mvIMPACT import acquire

SERIAL = "181642137271"

dm = acquire.DeviceManager()

dev = None
for i in range(dm.deviceCount()):
    d = dm.getDevice(i)
    if d.serial.read() == SERIAL:
        dev = d
        break

if dev is None:
    raise RuntimeError("NIR camera not found")

dev.open()

fi = acquire.FunctionInterface(dev)

fi.imageRequestSingle()

req_nr = fi.imageRequestWaitFor(5000)

print("request_nr =", req_nr)

req = fi.getRequest(req_nr)

try:
    print("isOK =", req.isOK)
    print("width =", req.imageWidth.read())
    print("height =", req.imageHeight.read())
    print("channels =", req.imageChannelCount.read())
    print("pixel format =", req.imagePixelFormat.readS())
except Exception as e:
    print(f"{e}")
fi.imageRequestUnlock(req_nr)

dev.close()


#%%
from mvIMPACT import acquire

dm = acquire.DeviceManager()
#%%
for i in range(dm.deviceCount()):
    d = dm.getDevice(i)
    print(i, d.serial.read(), d.product.read())
#%%

dev = dm.getDevice(1)

print(dev.serial.read(), dev.product.read())

dev.open()
#%%
fi = acquire.FunctionInterface(dev)

for _ in range(3):
    fi.imageRequestSingle()

req_nr = fi.imageRequestWaitFor(5000)

if not fi.isRequestNrValid(req_nr):
    raise RuntimeError("Timeout")

req = fi.getRequest(req_nr)

print("isOK:", req.isOK)
print("width:", req.imageWidth.read())
print("height:", req.imageHeight.read())
print("pixel format:", req.imagePixelFormat.readS())
print("image size:", req.imageSize.read())

fi.imageRequestUnlock(req_nr)

dev.close()