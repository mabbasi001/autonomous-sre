//go:build darwin

package collectors

import "syscall"

func diskUsedPercent(path string) (float64, error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, err
	}
	total := st.Blocks * uint64(st.Bsize)
	free := st.Bavail * uint64(st.Bsize)
	if total == 0 {
		return 0, nil
	}
	return (1 - float64(free)/float64(total)) * 100, nil
}
