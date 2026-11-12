"""Internal build permissions and network boundaries. Full keeps its existing controls."""
from .web import NAMESPACE


def resources(api_ip, dns_ips=()):
    def item(api,kind,name,**values):
        return {'apiVersion':api,'kind':kind,'metadata':{'name':name,'namespace':NAMESPACE},**values}
    selector={'matchLabels':{'app':'autokaggle-lite-build'}}
    return [
        item('v1','ServiceAccount','lite-builder-control',automountServiceAccountToken=True),
        item('rbac.authorization.k8s.io/v1','Role','lite-builder-control',rules=[
            {'apiGroups':['batch'],'resources':['jobs'],'verbs':['create','get','delete']},
            {'apiGroups':[''],'resources':['pods','pods/log'],'verbs':['get','list']}]),
        item('rbac.authorization.k8s.io/v1','RoleBinding','lite-builder-control',
            subjects=[{'kind':'ServiceAccount','name':'lite-builder-control','namespace':NAMESPACE}],
            roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'lite-builder-control'}),
        item('networking.k8s.io/v1','NetworkPolicy','lite-build-boundary',spec={
            'podSelector':selector,'policyTypes':['Ingress','Egress'],'ingress':[],
            'egress':[
                {'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}}}, *[{'ipBlock':{'cidr':ip+'/32'}} for ip in dns_ips]],
                 'ports':[{'port':53,'protocol':'UDP'},{'port':53,'protocol':'TCP'}]},
                {'to':[{'podSelector':{'matchLabels':{'app':'autokaggle-lite'}}}],
                 'ports':[{'port':32768,'endPort':60999,'protocol':'TCP'}]},
                {'to':[{'ipBlock':{'cidr':'0.0.0.0/0','except':['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','127.0.0.0/8','100.64.0.0/10']}}],
                 'ports':[{'port':443,'protocol':'TCP'}]}]}),
        item('networking.k8s.io/v1','NetworkPolicy','lite-build-gateway',spec={
            'podSelector':{'matchLabels':{'app':'autokaggle-lite'}},'policyTypes':['Ingress','Egress'],
            'ingress':[{'from':[{'podSelector':selector}],'ports':[{'port':32768,'endPort':60999,'protocol':'TCP'}]}],
            'egress':[{'to':[{'ipBlock':{'cidr':api_ip+'/32'}}],'ports':[{'port':6443,'protocol':'TCP'},{'port':443,'protocol':'TCP'}]}]})]
