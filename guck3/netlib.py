import paramiko
import telnetlib
import time
import subprocess


def ssh_connect(state_data):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(state_data.NET_CONFIG["host"], username=state_data.NET_CONFIG["ssh_user"],
                    password=state_data.NET_CONFIG["ssh_pass"])
        state_data.SSH = ssh
        return ssh
    except Exception:
        state_data.SSH = None
        return False


def services_restart(state_data):
    ssh = state_data.SSH
    try:
        transport = ssh.get_transport()
        transport.send_ignore()
    except Exception:
        ssh = ssh_connect(state_data)
        if not ssh:
            return "Cannot ssh to pfsense box @ " + state_data.NET_CONFIG["host"]
    # ssh into pfsense and di ifconfig up / down
    restart_php = "/etc/rc.php-fpm_restart"
    restart_webui = "killall -9 php; killall -9 lighttpd; /etc/rc.restart_webgui"
    restart_unbound = "pfSsh.php playback svc restart unbound"
    try:
        # restart php
        stdin, stdout, stderr = ssh.exec_command(restart_php)
        stdout.channel.recv_exit_status()
        # wait 2 sec.
        time.sleep(2)
        # restart webui
        stdin, stdout, stderr = ssh.exec_command(restart_webui)
        stdout.channel.recv_exit_status()
        # wait 2 sec.
        time.sleep(2)
        # restart unbound
        stdin, stdout, stderr = ssh.exec_command(restart_unbound)
        stdout.channel.recv_exit_status()
        return "services restart: SUCCESS!"
    except Exception as e:
        return "services restart: FAILURE - " + str(e)


# this re-inits the interface on pfsense (ifconfig igb2 down / up)
# write def get_status_for_if(!!)
def ifrestart(state_data, if0):
    pfsense_if = if0["pfsense_name"]
    ssh = state_data.SSH
    try:
        transport = ssh.get_transport()
        transport.send_ignore()
    except Exception:
        ssh = ssh_connect(state_data)
        if not ssh:
            return "Cannot ssh to pfsense box @ " + state_data.NET_CONFIG["host"]
    # ssh into pfsense and di ifconfig up / down
    downcmd = "ifconfig " + pfsense_if + " down"
    upcmd = "ifconfig " + pfsense_if + " up"
    # ifconfig down
    # wait until 100% packet loss on 192.168.2.1 (modem itself)
    # ifconfig up --> Achtung sometime stops unbound(s.u.)
    # wait until < 50% packet loss!
    # restart php-fm / webgui autom.
    # restart webgui
    # [2.4.5-RELEASE][admin@pfSense.iv.at]/root: pfSsh.php playback svc status unbound
    #             Service unbound is running.
    try:
        # send "if down"
        stdin, stdout, stderr = ssh.exec_command(downcmd)
        stdout.channel.recv_exit_status()
        # wait 10 sec.
        time.sleep(10)
        # send "if up"
        stdin, stdout, stderr = ssh.exec_command(upcmd)
        stdout.channel.recv_exit_status()
        return "interface restart for " + pfsense_if + ": SUCCESS!"
    except Exception as e:
        return "interface restart for " + pfsense_if + ": FAILURE - " + str(e)


# this reboots the modem via telnet(e.g. if there is not LTE connection)
def modemrestart(if0):
    host = if0["gateway_ip"]
    password = if0["gateway_pass"]
    timeout0 = 10
    # log in
    try:
        tn = telnetlib.Telnet(host, timeout=timeout0)
        tn.read_until(b"password:", timeout=timeout0)  # b'\r\r\npassword:'
        tn.write(password.encode("ascii") + b"\n")
    except Exception as e:
        return "modemrestart error: #1 - password / " + str(e)
    # send cmd "dev reboot"
    try:
        tn.read_until(b"(conf)#", timeout=timeout0)  # except EOFError as e, dann fail!!
        tn.write(b"dev reboot\n")
        # tn.write(b"help\n")
        # tn.write(b"logout\n")
    except Exception as e:
        return "modemrestart error: #2 - dev reboot / " + str(e)
    # read_all
    try:
        ret = tn.read_all().decode('ascii')
    except Exception as e:
        return "modemrestart error: #3 - read_all / " + str(e)
    try:
        if "dev reboot" in ret:
            return "executing 'dev reboot' on " + if0["name"]
        else:
            raise EOFError("telnet communication error!")
    except Exception as e:
        return "modemrestart error: #4 - " + str(e)


def get_net_status(state_data):
    ret = "------- Network Status -------"
    ssh = state_data.SSH
    try:
        transport = ssh.get_transport()
        transport.send_ignore()
    except Exception:
        ssh = ssh_connect(state_data)
        state_data.SSH = ssh
        if not ssh:
            ret += "\nCannot connect to pfsense box @ " + state_data.NET_CONFIG["host"]
    for if0 in state_data.NET_CONFIG["interfaces"]:
        ret += "\n" + if0["name"] + "/" + if0["pfsense_name"]
        # get external ip for dns
        dns_command = ["nslookup", if0["dns"]]
        try:
            resp = subprocess.Popen(dns_command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            resp_stdout = resp.stdout.readlines()
            resp_stderr = resp.stderr.readlines()
            dns_status = "N/A"
            for std in resp_stdout:
                std0 = std.decode("utf-8")
                if "Address: " in std0 and "#53" not in std0:
                    dns_status = (std0.split("Address: ")[-1]).rstrip("\n")
                    break
            ret += " (public: " + dns_status + ")"
        except Exception:
            ret += " (public: N/A)"
        if not ssh:
            continue
        # check if gateway reachable
        gateway_command = ["ping", "-c", "1", "-W 3", if0["gateway_ip"]]
        gw_status = "up"
        try:
            resp = subprocess.Popen(gateway_command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            resp_stdout = resp.stdout.readlines()
            resp_stderr = resp.stderr.readlines()
            # print(">> stdout >>", if0["name"], resp_stdout)
            # print(">> stderr >>", if0["name"], resp_stderr)
            for err in resp_stderr:
                if err.decode("utf-8"):
                    gw_status = "down"
                    break
            if gw_status == "up":
                gw_status = "down"
                for std in resp_stdout:
                    std0 = std.decode("utf-8")
                    if "1 received" in std0:
                        gw_status = "up"
                        break
            ret += "\n   Modem:  " + gw_status + " (ping to " + if0["gateway_ip"] + ")"
        except Exception as e:
            ret += "\n   Modem:   cannot detect, " + str(e) + " (ping to " + if0["gateway_ip"] + ")"
        if not ssh:
            continue
        # check ping from pfsense interface
        interface_command = "ping -v -c 1 -W 3 -S " + if0["interface_ip"] + " 8.8.8.8"
        ifstatus = "up"
        try:
            stdin, stdout, stderr = ssh.exec_command(interface_command)
            stdout.channel.recv_exit_status()
            resp_stdout = stdout.readlines()
            resp_stderr = stderr.readlines()
            # check if stderr
            for err in resp_stderr:
                if err:
                    ifstatus = "down"
                    break
            # check stdout if ok
            dt = "-"
            if ifstatus == "up":
                ifstatus = "down"
                for std in resp_stdout:
                    if ("1 packets received" in std) and ("0.0%" in std):
                        ifstatus = "up"
                    if "round-trip" in std:
                        try:
                            dt = std.split("round-trip min/avg/max/stddev = ")[-1]
                            dt = (dt.split("/")[1]).split(".")[0]
                        except Exception:
                            dt = "-"
            ret += "\n   Internet: " + ifstatus + " (ping from " + if0["interface_ip"] + " to 8.8.8.8 @ " + dt + "ms)"
        except Exception as e:
            ssh = ssh_connect(state_data)
            state_data.SSH = ssh
            ret += "\n   Internet: cannot detect, " + str(e) + " (ping from " + if0["interface_ip"] + " to 8.8.8.8)"
    return ret
