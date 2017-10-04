
#!/usr/bin/env python

from datetime import datetime
import sys
import os

import numpy as np
import matplotlib.pyplot as plt

import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.utils.data as data_utils

import torch.cuda

from tensorboard import SummaryWriter

class DeepRankConvNet():

	'''
	Convolutional Neural Network for DeepRank

	ARGUMENTS

	data_set
		
		Data set generated by the DeepRankDataSet
		data_set = DeepRankDataSet( ... )

	model

		definition of the NN to use. Must subclass nn.Module.
		See examples in model2D.py and model3d.py

	model_type : '2d' or '3d'

		Specify if we consider a 3D or a 2D convnet 
		This ust matches the model used in the training
		if we specif a 2d CNN the data set is automatically covnerted
		to the correct format.

	proj2d : 0,1 or 2

		specify wich axis is conisdered as a channels during the conversion from
		3d to 2d data type.
		0 -> x-axis is a channel i.e the images are in the yz plane
		1 -> y-axis is a channel i.e the images are in the xz plane
		1 -> z-axis is a channel i.e the images are in the xy plane
	
	task : 'ref' or 'class'

		Task to perform either
		'reg'   for regression 
		'class' for classification
		The loss function, the format of the targets and plot functions
		will be autmatically adjusted dependinf on the task

	tensorboard : 0/1

		Boolean to allow export in the tensorboard format.
		if set to true the logdir will be written in a dir called ./runs/
		type 
			tensorboard --logdir ./runs/ 
		to start tensorboard.
		Open a web browser and go to localhost:6006 to visualize the data

	plot : True/False

		So fat only a scatter plots of the outputs VS targets
		for training and validatiion set is exported.

	outdir

		output directory where all the files will be written

	USAGE 

		net = DeepRankConvNet( ... )
		(optional) net.optimiser = optim.Adam( ... )
		(optional) net.criterion = nn.CrossEntropy( .... )
		net.train( nepoch=50 )

	'''

	def __init__(self,data_set,model,model_type='3d',proj2d=0,
		         task=None,tensorboard=True,plot=True,outdir='./'):


		# Check if CUDA works
		self.cuda = torch.cuda.is_available() 

		# check if CUDA works
		if self.cuda:
			print(' --> CUDA detected : Using GPUs')
		else:
			print(' --> NO CUDA deteceted : Using CPUs')

		#data set and model
		self.data_set = data_set

		# convert the data to 2d if necessary
		if model_type == '2d':
			data_set.convert_dataset_to2d(proj2d=proj2d)

		# load the model
		self.net = model(data_set.input_shape)

		# cuda compatible
		if self.cuda:
			self.net = self.net.cuda()

		# task to accomplish 
		self.task = task

		# Set the loss functiom
		if self.task=='reg':
			self.criterion = nn.MSELoss()
			self._plot_scatter = self._plot_scatter_reg

		elif self.task=='class':
			self.criterion = nn.CrossEntropyLoss()
			self._plot_scatter = self._plot_scatter_class

		else:
			print("Task " + self.task +"not recognized.\nOptions are \n\t 'reg': regression \n\t 'class': classifiation\n\n")
			sys.exit()

		# set the optimizer
		self.optimizer = optim.SGD(self.net.parameters(),lr=0.005,momentum=0.9,weight_decay=0.001)

		# options for outputing the results
		self.tensorboard = tensorboard

		# output directory
		self.outdir = outdir
		if not os.path.isdir(self.outdir):
			os.mkdir(outdir)

		print('\n')
		print('='*40)
		print('=\t Convolution Neural Network')
		print('=\t model     : %s' %model_type)
		print('=\t CNN       : %s' %model.__name__)
		print('=\t features  : %s' %" / ".join([key for key,_ in self.data_set.select_feature.items()]))
		print('=\t targets   : %s' %self.data_set.select_target)
		print('='*40,'\n')	

	def train(self,nepoch=50, divide_set=[0.8,0.1,0.1], train_batch_size = 10, preshuffle = True,plot_intermediate=True):

		'''
		Perform a simple training of the model. The data set is divided in training/validation sets

		ARGUMENTS

		nepoch : Int. number of iterations to go through the training 

		divide_set : the percentage assign to the training, validation and test set.

		train_batch_size : the mini batch size for the training
		
		preshuffle. Boolean Shuffle the data set before dividing it.

		plot_intermediate : plot scatter plots during the training

		'''

		if self.tensorboard:
			tbwriter = SummaryWriter('runs/'+datetime.now().strftime('%B%d  %H:%M:%S'))
		else:
			tbwriter = None

		# divide the set in train+ valid and test
		index_train,index_valid,index_test = self._divide_dataset(divide_set,preshuffle)

		# print the final; scatter plot
		self._plot_scatter(self.outdir+"/initial_prediction.png", indexes = [index_train,index_valid,index_test])
		
		# train the model
		self._train(index_train,index_valid,nepoch=nepoch,train_batch_size=train_batch_size,tensorboard_writer=tbwriter,plot_intermediate=plot_intermediate)

		# test the model
		self._test(index_test)

		# print the final; scatter plot
		self._plot_scatter(self.outdir+"/final_prediction.png", indexes = [index_train,index_valid,index_test])

		# close the writers	
		if self.tensorboard:
			tbwriter.close()


	def train_montecarlo(self,nmc=2,nepoch=50, divide_set=[0.8,0.1,0.1], train_batch_size = 10, preshuffle = True):

		'''
		Perform a monte carlo cross validation calculation

		ARGUMENTS

		nmc 		: Int The number of MC iterations

		nepoch : Int. number of iterations to go through the training

		divide_set : the percentage assign to the training, validation and test set. 

		train_batch_size : the mini batch size for the training
		
		preshuffle. Boolean Shuffle the data set before dividing it.
		'''

		if self.tensorboard:
			tbwriter = SummaryWriter('runs/'+datetime.now().strftime('%B%d  %H:%M:%S'))
		else:
			tbwrite = None

		# divide the indexes in train+valid and test
		index_train, index_valid, index_test = self._divide_dataset(divide_set,preshuffle)
		ntrain = len(index_train)

		# loop over the MC iterations
		lparam = []
		for imc in range(nmc):

			print("\n===============================================")
			print("=== %02d/%02d of Monte Carlo cross validation" %(imc+1,nmc))
			print("===============================================")

			# train the model
			lparam.append(self._train(index_train,index_valid,nepoch=nepoch,train_batch_size=train_batch_size,tensorboard_writer=tbwriter))
			
			# test the model
			self._test(index_test)

			# plot the final figure of merit
			self._plot_scatter(self.outdir+'/prediction_mc_%02d.png' %(imc+1), indexes = [index_train,index_valid,index_test])

			# shuffle the training / validation indexes
			index_train_valid = index_valid.tolist()+index_train.tolist()
			np.random.shuffle(index_train_valid)
			train_loader = data_utils.DataLoader(self.data_set,batch_size=train_batch_size,sampler=data_utils.sampler.SubsetRandomSampler(index_train_valid[:ntrain]))
			valid_loader = data_utils.DataLoader(self.data_set,batch_size=1,sampler=data_utils.sampler.SubsetRandomSampler(index_train_valid[ntrain:]))

			# reinit the parameters
			self._reinit_parameters()


		print("\n===============================================")
		print("===       Average of all the models" )
		print("===============================================")

		# apply the average parameters
		self._apply_average_parameters(lparam)

		# test and plot the average model
		self._test(index_test)
		self._plot_scatter(self.outdir+"/final_prediction.png",indexes = [index_train,index_valid,index_test])

		# close the writers	
		if self.tensorboard:
			tbwriter.close()

	def train_kfold(self,k=2,nepoch=50, divide_set=[0.8,0.1,0.1], train_batch_size = 10, preshuffle = True):

		'''
		Perform a kfold cross validation of the model. 
		The data set is divided in k folds in each fold k-1 folds are used as training
		and the remaining as validation.

		ARGUMENTS

		k 		: Int The number of fold

		nepoch : Int. number of iterations to go through the training

		divide_set : the percentage assign to the training, validation and test set. 

		train_batch_size : the mini batch size for the training
		
		preshuffle. Boolean Shuffle the data set before dividing it.
		'''

		if self.tensorboard:
			tbwriter = SummaryWriter('runs/'+datetime.now().strftime('%B%d  %H:%M:%S'))
		else:
			tbwrite = None


		# divide the indexes in train+valid and test
		index_train, index_valid, index_test = self._divide_dataset(divide_set,preshuffle)

		# get the possible conf of train and valid
		indexes_train, indexes_valid = self._kfold_index(k,index_train.tolist()+index_valid.tolist())

		# perform the k-fold cross validation
		lparam = []
		for ik,(index_train,index_valid) in enumerate(zip(indexes_train,indexes_valid)):

			print("\n===============================================")
			print("=== %02d of %02d-fold cross validation" %(ik+1,k))
			print("===============================================")

			# train the model
			lparam.append(self._train(index_train,index_valid,nepoch=nepoch,train_batch_size=train_batch_size,tensorboard_writer=tbwriter))

			# test the model
			self._test(index_test)

			# plot the final figure of merit
			self._plot_scatter(self.outdir+'/prediction_%dfoldcv_%d.png' %(k,ik+1), indexes = [index_train,index_valid,index_test])

			# reinit the parameters
			self._reinit_parameters()

		print("\n===============================================")
		print("=== Average all the models" )
		print("===============================================")

		# apply the average parameters
		self._apply_average_parameters(lparam)

		# test and plot the average model
		self._test(index_test)
		self._plot_scatter(self.outdir+"/final_prediction.png",indexes = [index_train,index_valid,index_test])

		# close the writers	
		if self.tensorboard:
			tbwriter.close()

		
	def _divide_dataset(self,divide_set, preshuffle):

		'''
		Divide the data set in atraining validation and test
		according to the percentage in divide_set
		Retun the indexes of  each set
		'''

		# get the indexes of the train/validation set
		ind = np.arange(self.data_set.__len__())
		ntot = len(ind)

		if preshuffle:
			np.random.shuffle(ind)

		# size of the subset
		ntrain = int( float(ntot)*divide_set[0] )	
		nvalid = int( float(ntot)*divide_set[1] )
		ntest  = int( float(ntot)*divide_set[2] )

		# indexes
		index_train = ind[:ntrain]
		index_valid = ind[ntrain:ntrain+nvalid]
		index_test = ind[ntrain+nvalid:]

		return index_train,index_valid,index_test


	def _kfold_index(self,k,index_train_valid):

		'''
		Return the indexes of the training and validation set
		in the frame of a k-fold cross validation training
		'''

		# get the indexes of the train/validation set
		ntot = len(index_train_valid)

		# size of the subset
		subsize = int( float(ntot)/k)

		# get the indexes
		fold_index = []
		for ik in range(k):
			fold_index.append(list(range(ik*subsize,(ik+1)*subsize)))

		indexes_train, indexes_valid = [],[]
		for ik in range(k):
			index_tmp= []
			for iik in range(k):
				if iik != ik:
					index_tmp += [index_train_valid[j] for j in fold_index[iik]]
					
			indexes_train.append(index_tmp)
			indexes_valid.append( [index_train_valid[j] for j in fold_index[ik]])
			
		return indexes_train,indexes_valid


	def _train(self,index_train,index_valid,nepoch = 50,train_batch_size = 5,tensorboard_writer = None,plot_intermediate=False):

		'''
		Train the model 
	
		Arguments
		
		index_train : the indexes of the training set
		index_valid : the indexes of the validation set
		nepoch : number of epochs to be performed
		train_batch_size : the mini batch size for the training
		tensorboard_write : the writer for tensor board
		'''

		# printing options
		nprint = int(nepoch/10)

		# store the length of the training set
		ntrain = len(index_train)

		# create the sampler
		train_sampler = data_utils.sampler.SubsetRandomSampler(index_train)
		valid_sampler = data_utils.sampler.SubsetRandomSampler(index_valid)

		#  create the loaders
		train_loader = data_utils.DataLoader(self.data_set,batch_size=train_batch_size,sampler=train_sampler)
		valid_loader = data_utils.DataLoader(self.data_set,batch_size=1,sampler=valid_sampler)


		# training loop
		for epoch in range(nepoch):

			print('\n: epoch %03d ' %epoch + '-'*50)
			
			# train the model
			self.train_loss = self._epoch(train_loader,train_model=True)
			
			# validate the model
			self.valid_loss = self._epoch(valid_loader,train_model=False)

			# write the histogramm for tensorboard
			if self.tensorboard:
				self._export_tensorboard(tensorboard_writer,epoch)

			# plot the scatter plots
			if plot_intermediate and epoch%nprint == nprint-1:
				self._plot_scatter(self.outdir+"/prediction_%03d.png" %epoch, loaders = [train_loader,valid_loader])

			# talk a bit
			print('  training loss : %1.3e \t validation loss : %1.3e' %(self.train_loss, self.valid_loss))


		return torch.cat([param.data.view(-1) for param in self.net.parameters()],0)


	def _test(self,index_test):

		# test the model
		test_sampler = data_utils.sampler.SubsetRandomSampler(index_test)
		test_loader = data_utils.DataLoader(self.data_set,batch_size=1,sampler=test_sampler)
		test_loss = self._epoch(test_loader,train_model=False)
		print('\n-->\n-->\t\t Test loss : %1.3e\n-->' %test_loss)


	def _epoch(self,data_loader,train_model=True):

		'''
		Perform one single epoch iteration over a data loader
		The option train is True or False and controls
		if the model should be trained or not on the data
		The loss of the model is returned
		'''

		running_loss = 0
		for (inputs,targets) in data_loader:

			# get the data
			inputs,targets = self._get_variables(inputs,targets)

			# zero gradient
			if train_model:
				self.optimizer.zero_grad()

			# forward + loss
			outputs = self.net(inputs)
			loss = self.criterion(outputs,targets)
			running_loss += loss.data[0]

			# backward + step
			if train_model:
				loss.backward()
				self.optimizer.step()

		return running_loss


	def _reinit_parameters(self):

		'''
		Reinitialize the parameters of the model with a normal distribution
		'''

		for name,param in self.net.named_parameters():
			nn.init.normal(param,mean=0,std=0.1)


	def _apply_average_parameters(self,param_list):

		'''
		Average the parameters contained in the param_list
		and apply the average to the model
		This is usefull at the end of multiple training
		to get the 'final' model and test its performance 
		'''

		avg_param = torch.zeros(param_list[0].size())
		nparam = len(param_list)		
		for param in param_list:
			avg_param += param/nparam

		offset = 0
		for param in self.net.parameters():
			param.data.copy_(avg_param[offset:offset+param.nelement()].view(param.size()))
			offset += param.nelement()

	def _get_variables(self,inputs,targets):

		'''
		Convert the inout/target in Variables
		the format is different for regression where the targets are float
		and classification where they are int.
		'''

		# get the varialbe as float by default
		inputs,targets = Variable(inputs),Variable(targets).float()

		# change the targets to long for classification
		elif self.task == 'class':
			targets =  targets.long()

		# if cuda is available
		if self.cuda:
			inputs = inputs.cuda()
			targets = targets.cuda()

		return inputs,targets

	def _plot_scatter_reg(self,figname,loaders=None,indexes=None):

		'''
		Plot a scatter plots of predictions VS targets useful '
		to visualize the performance of the training algorithm 
		
		We can plot either from the loaders or from the indexes of the subset
		
		loaders should be either None or a list of loaders of maxsize 3
		loaders = [train_loader,valid_loader,test_loader]

		indexes should be a list of indexes list of maxsize 3
		indexes = [index_train,index_valid,index_test]
		'''

		# check if we have loaders
		if loaders is None:

			# check if we have indexes
			if indexes is None:
				print('-> Error during scatter plot, you must provide either loaders or indexes')
				return 

			# create the loaders
			loaders = []
			for iind in range(len(indexes)):
				loaders.append(data_utils.DataLoader(self.data_set,sampler=data_utils.sampler.SubsetRandomSampler(indexes[iind])))
			
		color_plot = ['red','blue','green']
		labels = ['Train','Valid','Test']

		fig,ax = plt.subplots()	
		ax.plot([0,1],[0,1])

		for idata,data_loader in enumerate(loaders):

			# storage for ploting
			plot_out,plot_targ = [],[]

			for (inputs,targets) in data_loader :

				inputs,targets = self._get_variables(inputs,targets)
				outputs = self.net(inputs)
				plot_out +=  outputs.data.numpy().tolist()
				plot_targ += targets.data.numpy().tolist()

			ax.scatter(plot_targ,plot_out,c = color_plot[idata],label=labels[idata])	

		legend = ax.legend(loc='upper left')
		ax.set_xlabel('Targets')
		ax.set_ylabel('Predictions')
		fig.savefig(figname)


	def _plot_scatter_class(self,figname,loaders=None,indexes=None):

		'''
		Plot a scatter plots of predictions VS targets useful '
		to visualize the performance of the training algorithm 
		This is only usefull in regression tasks
		
		We can plot either from the loaders or from the indexes of the subset
		
		loaders should be either None or a list of loaders of maxsize 3
		loaders = [train_loader,valid_loader,test_loader]

		indexes should be a list of indexes list of maxsize 3
		indexes = [index_train,index_valid,index_test]
		'''


		# check if we have loaders
		if loaders is None:

			# check if we have indexes
			if indexes is None:
				print('-> Error during scatter plot, you must provide either loaders or indexes')
				return 

			# create the loaders
			loaders = []
			for iind in range(len(indexes)):
				loaders.append(data_utils.DataLoader(self.data_set,sampler=data_utils.sampler.SubsetRandomSampler(indexes[iind])))

		color_plot = ['red','blue','green']
		labels = ['Train','Valid','Test']

		verts = list(zip([-1., 1., 1., -1.], [-1., -1., 1., -1.]))
		marker = [(5,1),(verts,0),'o']
		area = [50,50,100]
		fig,ax = plt.subplots()	
		ax.plot([-1,1],[0,0],c='black')
		ax.plot([0,0],[-1,1],c='black')
		ax.set_xlim([-1.25,1.25])
		ax.set_ylim([-1.25,1.25])

		angles = np.linspace(0,2*np.pi,50)
		for r in [0.25,0.5,0.75,1]:
			ax.plot(r*np.cos(angles),r*np.sin(angles),'--',linewidth=0.5,c='black')

		for idata,data_loader in enumerate(loaders):

			# storage for ploting
			plot_out,plot_targ = [],[]
			ndata = data_loader.sampler.__len__()
			angles = np.linspace(0,2*np.pi,ndata)
			k = 0
			for (inputs,targets) in data_loader :

				inputs,targets = self._get_variables(inputs,targets)
				outputs = self.net(inputs)

				tar = targets.data.numpy()
				out = outputs.data.numpy()

				for pts,t in zip(out,tar):
					col = color_plot[int(t)]
					angle = angles[k]
					r = F.softmax(torch.FloatTensor(pts)).data.numpy()
					ax.scatter(r[1]*np.cos(angle),r[1]*np.sin(angle),s=area[idata],c=col,alpha=0.5,marker=marker[idata])
					k+=1
		fig.savefig(figname)


	def _export_tensorboard(self,tensorboard_writer,epoch):

		'''
		Export the data of the model to tensorboard for post visualisation
		'''

		for name,param in self.net.named_parameters():
			tensorboard_writer.add_histogram(name, param.clone().cpu().data.numpy(), epoch)

			# write the losses for tensorboard
			tensorboard_writer.add_scalar('train_loss',self.train_loss,epoch)
			tensorboard_writer.add_scalar('valid_loss',self.valid_loss,epoch)



#-------------------------------------------------------------------------------


if __name__ == "__main__":


	from deeprank.learn import DeepRankDataSet, DeepRankConvNet

	# create the sets
	data_folder = '../training_set/'
	data_set = DeepRankDataSet(data_folder,
                               filter_dataset = 'decoyID.dat',
                               select_feature={'AtomicDensities' : 'all'},
                               select_target='haddock_score')

	# create the network
	model = DeepRankConvNet(data_set,
                            SmallConvNet3D,
                            model_type='3d',
                            task='reg',
                            tensorboard=False,
                            outdir='./test_out/')

	# change the optimizer
	model.optimizer = optim.SGD(model.net.parameters(),
                                lr=0.001,
                                momentum=0.9,
                                weight_decay=0.005)

	# start the training
	model.train(nepoch = 250)

	






