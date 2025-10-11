"""Test script for download limiter functionality."""
from src.komuzik.download_limiter import DownloadLimiter


def test_download_limiter():
    """Test the download limiter."""
    limiter = DownloadLimiter()
    
    # Test regular user
    regular_user = 123456789
    
    print(f"Testing regular user {regular_user}:")
    print(f"  Can download: {limiter.can_download(regular_user)}")
    
    # Start first download
    success = limiter.start_download(regular_user, "download1")
    print(f"  Started download1: {success}")
    print(f"  Active downloads: {limiter.get_active_count(regular_user)}")
    print(f"  Can start another: {limiter.can_download(regular_user)}")
    
    # Try to start second download (should fail)
    success = limiter.start_download(regular_user, "download2")
    print(f"  Started download2: {success}")
    print(f"  Active downloads: {limiter.get_active_count(regular_user)}")
    
    # Finish first download
    limiter.finish_download(regular_user, "download1")
    print(f"  Finished download1")
    print(f"  Active downloads: {limiter.get_active_count(regular_user)}")
    print(f"  Can download now: {limiter.can_download(regular_user)}")
    
    # Now can start another
    success = limiter.start_download(regular_user, "download3")
    print(f"  Started download3: {success}")
    print(f"  Active downloads: {limiter.get_active_count(regular_user)}")
    
    limiter.finish_download(regular_user, "download3")
    
    print("\nTesting unlimited user 782491733:")
    unlimited_user = 782491733
    
    print(f"  Is unlimited: {limiter.is_unlimited_user(unlimited_user)}")
    print(f"  Can download: {limiter.can_download(unlimited_user)}")
    
    # Start multiple downloads
    for i in range(5):
        success = limiter.start_download(unlimited_user, f"download{i}")
        print(f"  Started download{i}: {success}")
    
    print(f"  Active downloads: {limiter.get_active_count(unlimited_user)}")
    print(f"  Can still download: {limiter.can_download(unlimited_user)}")
    
    # Clean up
    for i in range(5):
        limiter.finish_download(unlimited_user, f"download{i}")
    
    print(f"\n✅ All tests completed successfully!")


if __name__ == "__main__":
    test_download_limiter()
