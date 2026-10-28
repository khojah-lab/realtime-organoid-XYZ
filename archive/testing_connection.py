# test_connection.py
from swiftCloudAuth import sv

# Test connection
try:
    print("Testing connection to SDSC Swift...")
    containers = list(sv.list())
    print(f"✓ Connected! Found {len(containers)} containers")
    
    # Create container if needed
    sv.post(container='microscopy_images')
    print("✓ Container 'microscopy_images' ready")
    
    # Upload test file
    with open('/tmp/test.txt', 'w') as f:
        f.write("SDSC test")
    with open('/tmp/test.txt', 'rb') as f:
        sv.upload('microscopy_images', [{
            'name': 'test.txt',
            'path': '/tmp/test.txt'
        }])
    print("✓ Test upload complete")
    
except Exception as e:
    print(f"✗ Error: {e}")