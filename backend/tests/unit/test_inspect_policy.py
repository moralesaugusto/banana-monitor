import pytest

from app.llm.inspect_policy import PolicyError, check_linux, check_proxmox_path, check_windows

LINUX_OK = [
    "uname -a",
    "ps aux",
    "ps -eo pid,user,cmd",
    "ss -tulpn",
    "df -h",
    "free -m",
    "journalctl -u ssh --since today -n 200",
    "journalctl -p err -b",
    "systemctl status ssh",
    "systemctl list-units --failed",
    "apt list --upgradable",
    "apt-get -s upgrade",
    "dnf check-update",
    "dpkg -l",
    "rpm -qa",
    "last -n 20",
    "lastb -n 20",
    "cat /var/log/auth.log",
    "tail -n 100 /var/log/syslog",
    "grep -i failed /var/log/auth.log",
    "grep -rn sshd /var/log",
    "find /tmp -newer /etc/passwd -type f",
    "sha256sum /usr/bin/ssh",
    "ls -la /home/user/.ssh",
    "cat /home/user/.ssh/authorized_keys",
    "crontab -l",
    "ip -s link",
    "ip addr show",
    "hostname",
    "getent passwd",
]

LINUX_BAD = [
    "",
    "   ",
    "uname -a; id",
    "uname -a && id",
    "uname -a | sh",
    "cat /etc/passwd > /tmp/x",
    "cat $(echo /etc/shadow)",
    "cat `id`",
    "cat /etc/pass*",
    "echo hi",
    "bash -c id",
    "sh",
    "python3 -c 1",
    "rm -rf /tmp/x",
    "curl http://example.com",
    "wget http://example.com",
    "/bin/ls",
    "./ls",
    "cat\n/etc/shadow",
    'grep "a b" /var/log/syslog',
    "cat '/etc/shadow'",
    "cat /etc/shadow",
    "cat /etc/gshadow",
    "cat /etc/sudoers",
    "cat /home/user/.ssh/id_ed25519",
    "cat /home/user/.ssh/id_rsa",
    "cat /root/key.pem",
    "cat /etc/ssl/private/server.key",
    "cat /proc/self/environ",
    "cat /proc/1/environ",
    "cat /opt/banana/backend/secrets/master.key",
    "cat /var/log/../../etc/shadow",
    "cat --file=/etc/shadow",
    "find / -exec id ;",
    "find / -delete",
    "find /tmp -fprint /tmp/x",
    "journalctl --rotate",
    "journalctl --vacuum-size=1M",
    "tail -f /var/log/syslog",
    "date -s 2020-01-01",
    "ss -K",
    "ps auxe",
    "ps e",
    "systemctl restart ssh",
    "systemctl stop ssh",
    "systemctl --user status x",
    "apt-get upgrade",
    "apt-get -s install curl",
    "apt-get -y upgrade",
    "apt install curl",
    "dnf install curl",
    "dpkg -i x.deb",
    "dpkg --remove ssh",
    "rpm -e ssh",
    "rpm -i x.rpm",
    "crontab -r",
    "crontab -e",
    "hostname evil",
    "ip link set eth0 down",
    "ip addr add 1.2.3.4/24 dev eth0",
    "ip route del default",
    "grep -r password /",
    "grep -r password /home",
    "file -C",
    "x " * 40,
    "a" * 400,
]


@pytest.mark.parametrize("command", LINUX_OK)
def test_linux_allows_read_only(command):
    assert check_linux(command) == " ".join(command.split())


@pytest.mark.parametrize("command", LINUX_BAD)
def test_linux_refuses(command):
    with pytest.raises(PolicyError):
        check_linux(command)


WINDOWS_OK = [
    "Get-Process",
    "Get-Service -Name Spooler",
    "Get-WinEvent -LogName Security -MaxEvents 50",
    "Get-NetTCPConnection -State Listen",
    "Get-LocalUser",
    "Get-HotFix",
    "Get-ScheduledTask",
    "Get-FileHash C:\\Windows\\System32\\cmd.exe",
    "Get-ChildItem C:\\Users",
    "Get-MpThreatDetection",
]

WINDOWS_BAD = [
    "",
    "Get-Process; Stop-Process -Id 1",
    "Get-Process | Stop-Process",
    "Get-Process & whoami",
    "Get-Process $(whoami)",
    "Invoke-Expression 1",
    "iex 1",
    "Set-Service -Name x -StartupType Disabled",
    "Remove-Item C:\\x",
    "Start-Process cmd",
    "New-LocalUser x",
    "Stop-Service x",
    "Get-Credential",
    "Get-Process -ComputerName other",
    "Get-Process -OutFile x",
    "Get-ChildItem -Recurse C:\\",
    "Get-Content C:\\Windows\\System32\\config\\SAM",
    "Get-Content C:\\Users\\a\\.ssh\\id_rsa",
    "Get-Content C:\\x\\cert.pfx",
    "Get-ItemProperty HKLM:\\SAM",
    "Get-Content ..\\..\\x",
    "Get-WinEvent -FilterHashtable @{LogName='Security'}",
    "Get-Process `n whoami",
    'Get-Content "C:\\x"',
]


@pytest.mark.parametrize("command", WINDOWS_OK)
def test_windows_allows_read_only_cmdlets(command):
    assert check_windows(command) == " ".join(command.split())


@pytest.mark.parametrize("command", WINDOWS_BAD)
def test_windows_refuses(command):
    with pytest.raises(PolicyError):
        check_windows(command)


@pytest.mark.parametrize(
    "path",
    [
        "/version",
        "/nodes",
        "/nodes/pve1/status",
        "/nodes/pve1/qemu",
        "/nodes/pve1/tasks",
        "/nodes/pve1/syslog",
        "/nodes/pve1/apt/update",
        "/nodes/pve1/qemu/100/status/current",
        "/nodes/pve1/lxc/101/config",
        "/cluster/resources",
    ],
)
def test_proxmox_allows_read_paths(path):
    assert check_proxmox_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "/access/users",
        "/access/ticket",
        "/nodes/pve1/qemu/100/status/stop",
        "/nodes/pve1/execute",
        "/nodes/pve1/qemu/100/agent/exec",
        "/nodes/../access/users",
        "/nodes/pve1/status?x=1",
        "/storage",
        "nodes",
        "",
    ],
)
def test_proxmox_refuses_everything_else(path):
    with pytest.raises(PolicyError):
        check_proxmox_path(path)
