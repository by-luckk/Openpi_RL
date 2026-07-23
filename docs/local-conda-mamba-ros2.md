# 本地 Miniconda/mamba 与 ROS2 topic 环境安装记录

日期：2026-06-30；检查人：agent。
目的：按用户要求在工作站安装系统级 Miniconda 和 mamba，默认使用 mamba；同时为本地接收 `/camera/head_right/image_rect/camera_info` 准备最小 ROS2 订阅环境。密码只通过 sudo 交互提示输入，未写入命令或文档。

## 1. 安装前检查

命令：

```bash
lsb_release -a
uname -a
which conda || true
which mamba || true
which ros2 || true
ls -ld /opt/miniconda3 /opt/conda 2>/dev/null || true
```

关键结论：

```text
Ubuntu 24.04.4 LTS (noble)
x86_64
conda/mamba/ros2: not found
/opt/miniconda3: not found
/opt/conda: not found
```

## 2. 系统级 Miniconda

命令：

```bash
curl -L -o /tmp/Miniconda3-latest-Linux-x86_64.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
sha256sum /tmp/Miniconda3-latest-Linux-x86_64.sh
sudo bash /tmp/Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda3
```

关键输出：

```text
2284bafb7863a23411b19874d216e237964d4b32dd9beb6807fa8b2d84570961  /tmp/Miniconda3-latest-Linux-x86_64.sh
installation finished.
```

结论：Miniconda 安装在 `/opt/miniconda3`，不是用户目录。

## 3. mamba 与默认配置

命令：

```bash
sudo /opt/miniconda3/bin/conda install -n base --override-channels -c conda-forge mamba conda-libmamba-solver -y
sudo /opt/miniconda3/bin/conda config --system --set solver libmamba
sudo /opt/miniconda3/bin/conda config --system --set channel_priority strict
sudo /opt/miniconda3/bin/conda config --system --add channels conda-forge
sudo ln -sf /opt/miniconda3/bin/conda /usr/local/bin/conda
sudo ln -sf /opt/miniconda3/bin/mamba /usr/local/bin/mamba
```

同时写入：

- `/etc/profile.d/miniconda.sh`
- `/etc/zsh/zshrc`
- `/etc/bash.bashrc`

用于让新 shell 自动加载 `/opt/miniconda3`，并通过 `mamba shell hook --root-prefix /opt/miniconda3` 支持 `mamba activate/deactivate`。该 hook 指向 `/opt/miniconda3`，不使用用户态 root prefix。

验证命令：

```bash
zsh -ic 'which mamba; mamba --version; conda --version; conda config --show solver channels channel_priority'
bash -ic 'which mamba; mamba --version; conda --version; conda config --show solver channels channel_priority'
zsh -ic 'mamba activate ros2-topic && which ros2 && ros2 topic --help | head -n 8'
bash -ic 'mamba activate ros2-topic && which ros2 && ros2 topic --help | head -n 8'
```

关键输出：

```text
/opt/miniconda3/bin/mamba
2.5.0
conda 26.5.3
solver: libmamba
channel_priority: strict
channels:
  - conda-forge
  - defaults
/opt/miniconda3/envs/ros2-topic/bin/ros2
usage: ros2 topic [-h] [--include-hidden-topics]
```

结论：新 zsh/bash 中 `mamba` 默认可用，且 `mamba activate ros2-topic` 可直接激活；`conda` 也已默认使用 libmamba solver。

## 4. ROS2 topic 最小环境

曾尝试安装较大的 `ros-jazzy-ros-base` 环境，但依赖链包含大体积仿真/图形相关包，下载到 `pybullet` 时耗时过长，中断后清理了半成品环境：

```bash
sudo /opt/miniconda3/bin/mamba env remove -n ros2-jazzy -y
```

实际采用最小订阅环境：

```bash
sudo /opt/miniconda3/bin/mamba create -y -n ros2-topic \
  --override-channels \
  -c conda-forge -c robostack-jazzy \
  ros-jazzy-ros2topic \
  ros-jazzy-sensor-msgs \
  ros-jazzy-rmw-fastrtps-cpp
```

关键输出：

```text
Prefix: /opt/miniconda3/envs/ros2-topic
Install: 207 packages
Total download: 0 B
Transaction finished
```

验证命令：

```bash
mamba run -n ros2-topic ros2 topic --help
mamba run -n ros2-topic python -c 'from sensor_msgs.msg import CameraInfo; print(CameraInfo.__name__)'
ls -ld /opt/miniconda3/envs/ros2-jazzy /opt/miniconda3/envs/ros2-topic
```

关键输出：

```text
Commands: bw delay echo find hz info list pub type
CameraInfo
ls: cannot access '/opt/miniconda3/envs/ros2-jazzy': No such file or directory
drwxr-xr-x ... /opt/miniconda3/envs/ros2-topic
```

结论：半成品 `ros2-jazzy` 已清理；可用环境是 `/opt/miniconda3/envs/ros2-topic`。

## 5. 本地接收机器人 camera_info 实测

命令：

```bash
ping -c 1 -W 1 192.168.25.1
mamba run -n ros2-topic bash -lc 'export ROS_DOMAIN_ID=0; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; ros2 topic list'
mamba run -n ros2-topic bash -lc 'export ROS_DOMAIN_ID=0; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; ros2 topic echo --once /camera/head_right/image_rect/camera_info'
timeout 15s zsh -ic 'mamba activate ros2-topic && export ROS_DOMAIN_ID=0 && export RMW_IMPLEMENTATION=rmw_fastrtps_cpp && ros2 topic echo --once /camera/head_right/image_rect/camera_info'
```

关键输出：

```text
64 bytes from 192.168.25.1: icmp_seq=1 ttl=64 time=0.352 ms
/camera/head_right/image_rect
/camera/head_right/image_rect/camera_info
header.frame_id: camera_xf6600_head_right
height: 352
width: 640
```

结论：本地工作站已能直接接收 `/camera/head_right/image_rect/camera_info`。后续使用时：

```bash
mamba activate ros2-topic
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ros2 topic echo --once /camera/head_right/image_rect/camera_info
```
