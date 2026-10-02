#include "exti.h"
#include "stm32f10x.h"
#include "sys.h"

/*
--------------------------按键EXTI操作-----------------------------
按键外部中断实现的过程：
	1.查看原理图，确定按键对应的端口及引脚---PC8、PC9配置为上拉输入引脚-->GPIOC
	2.确认对应的外部中断驱动是否勾选添加---EXTI
	3.RCC硬件时钟使能
	4.GPI0_Init初始化 --> stm32f10x_gpio.c   
	5.GPIO_EXTILineConfig执行外部中断线的配置 --> stm32f10x_gpio.c
	  AFIO挂载在APB2总线(AFIO配置)-->stm32f10x中文参考手册P28
	6.EXTI_Init初始化 --> stm32f10x_exti.c
	7.设置优先级分组--默认组2
	8.NVIC_Init初始化 --> misc.c
	9.书写中断响应函数
	10.上述操作完成后，编译并下载代码，然后按下按键观察LED灯是否有响应
*/

void key_exti_init(void)
{
	// GPIO
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;
	
	// 2.打开外设时钟  PC8--GPIOC  PC9--GPIOC
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);

	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_8 | GPIO_Pin_9;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;	// 引脚模式   上拉输入
	
	// 4.初始化GPIO
	GPIO_Init(GPIOC, &GPIO_InitStructure);
	
	// AFIO
	// 打开AFIO的时钟使能
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_AFIO, ENABLE);
	// 由于GPIO_PinSource8、GPIO_PinSource9其值无规则，不能使用按位或操作
	GPIO_EXTILineConfig(GPIO_PortSourceGPIOC, GPIO_PinSource8);
	GPIO_EXTILineConfig(GPIO_PortSourceGPIOC, GPIO_PinSource9);
	
	// EXTI
	// 针对外部中断的参数配置
	EXTI_InitTypeDef EXTI_InitStructure;
	EXTI_InitStructure.EXTI_Line = EXTI_Line8 | EXTI_Line9;	// 指定我们要配置的中断线--配置中断8、9号线
	EXTI_InitStructure.EXTI_Mode  = EXTI_Mode_Interrupt;	// 配置中断模式
	EXTI_InitStructure.EXTI_Trigger = EXTI_Trigger_Falling;	// 下降沿触发 
	EXTI_InitStructure.EXTI_LineCmd = ENABLE;	// 使能外部中断
	// 初始化EXTI
	EXTI_Init(&EXTI_InitStructure);
	
	// 配置NVIC
	NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2); // 确认分组
	
	NVIC_InitTypeDef NVIC_InitStructure;
	NVIC_InitStructure.NVIC_IRQChannel = EXTI9_5_IRQn; // 配置中断通道
	NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 0X0F; // 配置抢占优先级
	NVIC_InitStructure.NVIC_IRQChannelSubPriority = 0X0F; // 配置响应优先级
	NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE; // 使能中断通道
	// 初始化NVIC
	NVIC_Init(&NVIC_InitStructure);
}

/*中断响应函数的书写规范
	1.打开文件startup_stm32f10x_hd.s
	2.在文件中找到我们中断响应函数的函数名进行拷贝（P287）
	3.其函数的返回类型、形参列表都是void
	4.获取并判断中断状态，并判断中断是否触发
	5.书写中断触发后的代码
	6.操作完成后一定要清除中断标志位
*/

void EXTI9_5_IRQHandler(void)
{
	if(EXTI_GetITStatus(EXTI_Line8) == SET)	// 	if(EXTI_GetITStatus(EXTI_Line8) != RESET)
	{
		// 实现灯的灭操作
		PAout(8) = 1;
		
		// 清除中断标志位
		// 防止程序被卡死-- 如果不清除中断标志位，程序会一直申请中断，程序会不断响应中断，执行中断函数
		EXTI_ClearITPendingBit(EXTI_Line8);
	}	
	
		if(EXTI_GetITStatus(EXTI_Line9) == SET)	// 	if(EXTI_GetITStatus(EXTI_Line8) != RESET)
	{
		// 实现灯的亮操作
		PAout(8) = 0;
		
		// 清除中断标志位
		// 防止程序被卡死-- 如果不清除中断标志位，程序会一直申请中断，程序会不断响应中断，执行中断函数
		EXTI_ClearITPendingBit(EXTI_Line9);
	}	
}
