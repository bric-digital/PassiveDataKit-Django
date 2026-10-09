//Load common code that includes config, then load the app logic for this page.
requirejs(['./common'], function (common) {
    requirejs(["bootstrap", "bootstrap-datepicker", "moment", "jquery"], function (bootstrap, bs_datepicker, moment, jquery)
    {
    	window.$ = jquery;
    	window.moment = moment;
    	
		$.ajaxSetup({ 
			beforeSend: function(xhr, settings) 
			{
				if (!(/^http:.*/.test(settings.url) || /^https:.*/.test(settings.url))) 
				{
					// Only send the token to relative URLs i.e. locally.
					xhr.setRequestHeader("X-CSRFToken", $.cookie('csrftoken'));
				}
			}
		});

		$('[data-toggle="tooltip"]').tooltip();

		$('#sources_select_all').change(function() 
		{
			$(".source_checkbox").prop("checked", $(this).is(":checked"));
		});
		
		$('.group_select_members').change(function(eventObj)
		{
			 const id = $(this).attr('id')
			 
			$('.' + id).prop("checked", $(this).is(":checked"));
		});

		$('#generators_select_all').change(function() 
		{
			$(".generator_checkbox").prop("checked", $(this).is(":checked"));
		});
		
		$('#data_start').datepicker();
		$('#data_end').datepicker();

		$('#export_form').on('submit', function (e) {
			e.preventDefault();
			
			var self = $(this);

			const form = $(self.get(0)).find('input')
			
			let sources = []
			
			let payload = {}
			
			for (let i = 0; i < form.length; i++) {
				const input = $(form.get(i))
				
				const key = input.attr('name')
				const value = input.val()
				
				if (key !== undefined && value !== undefined) {
					if (key.startsWith('source_')) {
						if (value === 'on') {
							if (input.is(':checked')) {
								sources.push(key.replaceAll('source_', ''))
							}
						}
					} else {
						if (value === 'on') {
							if (input.is(':checked')) {
								payload[key] = value
							}
						} else {
							if (input.attr('type') === 'radio') {
								if (input.is(':checked')) {
									payload[key] = value
								}
							} else {
								payload[key] = value
							}
						}
					}
				}
			}
			
			payload['sources'] = sources.join(';')

			$.post(self.find('form').attr('action'), payload, function(response) {
				if (response.success) {
					alert('Export job request submitted.')
					window.location = `${window.location}`
				}
			});			
		});
	}); 
});