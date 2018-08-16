Name:      simengine-core
Version:   1
Release:   1
Summary:   SimEngine - Core
URL:       https://github.com/Seneca-CDOT/simengine
License:   GPLv3+

Source0:   %{name}-%{version}.tar.gz
BuildArch: noarch

#Requires: simengine-database, python-pysnmp, python-circuits, python-snmpsim, python3-libvirt
Requires: simengine-database, python3-libvirt

%description
Core files for SimEngine.

%prep
%autosetup -c %{name}

%build

%install
mkdir -p %{buildroot}%{_sharedstatedir}/%{name}/enginecore/script/
mkdir -p %{buildroot}%{_prefix}/lib/systemd/system/
cp -fRp data %{buildroot}%{_sharedstatedir}/%{name}/
cp -fRp enginecore %{buildroot}%{_sharedstatedir}/%{name}/enginecore/
cp -fp snmppub.lua %{buildroot}%{_sharedstatedir}/%{name}/enginecore/script/
cp -fp app.py %{buildroot}%{_sharedstatedir}/%{name}/enginecore/
cp -fp simengine-core.service %{buildroot}%{_prefix}/lib/systemd/system/
exit 0

%files
%{_sharedstatedir}/%{name}/data
%{_sharedstatedir}/%{name}/enginecore/script/snmppub.lua
%{_sharedstatedir}/%{name}/enginecore/app.py
%{_sharedstatedir}/%{name}/enginecore/enginecore
%attr(0644, root, root) %{_prefix}/lib/systemd/system/simengine-core.service

%post
systemctl daemon-reload
systemctl enable simengine-core.service --now

%changelog
* Thu Aug 16 2018 Chris Johnson <chris.johnson@senecacollege.ca>
- Updated dependencies

* Mon Jul 23 2018 Chris Johnson <chris.johnson@senecacollege.ca>
- Initial alpha test file